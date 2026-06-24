# Stimela: A Critical Assessment

Analysis conducted 2026-06-24. This is the opinionated companion to ANALYSIS.md.

## The Core Problem

Stimela started with a good idea: a **thin orchestrator** that runs astronomy
tools in containers with typed parameters. That's a valid, focused concept.
What it became is a 14.5k-line framework that reimplements half of a
programming language inside YAML.

The `Recipe` class alone is 1476 lines with **31 methods**, the longest being
187 lines. It handles finalization, alias management, prevalidation, assignment
propagation, for-loop orchestration, DAG construction, step restriction,
logging, and execution. This is not an orchestrator. This is an interpreter
for a home-grown language that happens to be serialized as YAML.

## Feature Creep Inventory

Every one of these features was added individually with good intent. Together
they form an accretion disk of complexity that makes the system nearly
impossible to reason about:

### The substitution system (`{recipe.param}`, `{.local}`, `=formulas`)

What started as simple variable interpolation grew into a full expression
evaluator. There are now **4 open bugs** in the substitution engine alone
(#293, #265, #282, #364) because the semantics are under-specified. Escaping
`{{` doesn't work (#265). Nested formulas don't evaluate (#293). Type
coercion breaks on complex types (#364). For-loop variables break
prevalidation (#282).

This is the predictable result of building a custom expression language
instead of using Python.

### `assign_based_on` — a switch statement in YAML

```yaml
assign_based_on:
  solver_type:
    calsuite:
      calibration.solver: quartical
    DEFAULT:
      calibration.solver: cubical
```

This is a YAML-encoded switch statement. It has 18 references across the
kitchen module. It adds ~50 lines of logic to `update_assignments()` for
looking up base variables, handling DEFAULT cases, cascading through config
sections. All of this could be a Python `if` statement in a recipe script.

### `nom_de_guerre` — parameter renaming

Parameters can have a `nom_de_guerre` — a different name used on the command
line than in the recipe schema. This exists because different tools use
different flag names for the same concept. It adds branching in 4 places
in `cab.py`. The sane solution is: name the parameter what the tool calls it.
If you need a common name, that's what aliases are for.

### `preamble` and `epilogue` — pre/post expressions

Steps can have `preamble` (expressions evaluated before running) and
`epilogue` (expressions evaluated after). These are evaluated in the
custom substitution engine. They're Python expressions encoded as YAML
strings. At this point you're writing Python with extra steps and worse
error messages.

### `wranglers` — regex-based output rewriting

```yaml
wranglers:
  "error reading file (.*)": DeclareError
  "WARNING: (.*)": ChangeSeverity WARNING
```

Regex-triggered stdout processors. Five wrangler types: Replace, Suppress,
ChangeSeverity, DeclareError, ParseOutput. These are clever, but they paper
over the real problem: tools with bad output formatting. This is the kind
of feature that feels useful for the person who adds it and becomes a
maintenance burden for everyone else. 6 open issues reference unexpected
wrangler behavior.

### `for_loop` with `scatter` and `output_elements`

Recipes can be for-loops. For-loops can scatter to process pools. Scattered
loops accumulate `output_elements` expressions. The `validate_for_loop`
method alone is 66 lines of validation logic for the various ways a for-loop
can be specified (`over` as input name, as literal list, as assigned variable).

`_iterate_loop_worker` is 150 lines and returns a **9-element tuple**:

```python
return (
    task_attrs,
    task_kwattrs,
    task_stats.collect_stats(),
    outputs,
    exception,
    tb,
    subprocess_logs,
    count,
    output_elements,
)
```

A 9-element tuple as a return value is a code smell visible from orbit.

### Alias system — the complexity multiplier

Aliases allow recipe parameters to be wired to step parameters. This sounds
simple. In practice:

- Aliases propagate **up** (step → recipe) and **down** (recipe → step)
- Propagation happens at prevalidation AND at runtime
- Implicit parameters add another propagation direction
- `_add_alias` is 147 lines and handles wildcards, multiple targets,
  input/output disambiguation, and category assignment
- The DEVNOTES.md is literally a 50-line prose essay trying to work out
  the correct alias propagation logic

When you need a design document to explain your parameter-passing model,
the model is too complex.

## Architecture Sins

### 1. Recipe is a god class

| Method | Lines | What it does |
|--------|-------|-------------|
| `_run` | 187 | Execution, for-loop dispatch, scatter pooling |
| `_iterate_loop_worker` | 150 | Single loop iteration (with subprocess support) |
| `_add_alias` | 147 | Alias resolution with wildcards |
| `prevalidate` | 144 | Multi-pass validation with alias propagation |
| `update_assignments` | 132 | Variable assignment with assign_based_on |
| `finalize` | 107 | Step instantiation, alias collection |

The Recipe class has more responsibilities than most microservices.

### 2. No backend protocol

Backends are modules with functions discovered via `getattr`. There is no
ABC, no Protocol, no interface definition. A new backend can be missing
`run()` and nobody knows until someone tries to use it. Docker and Podman
prove this — they're importable modules that can never execute anything.

### 3. Config defined inside a function

`StimelaConfig` and `StimelaLibrary` are defined as local classes inside
`load_config()` and then assigned to module globals. This makes them
invisible to type checkers, IDE autocomplete, and anyone reading the code
top-down.

### 4. OmegaConf everywhere

OmegaConf is used for everything: config, parameters, schemas, step
definitions, backend settings. The code is littered with `DictConfig`,
`OmegaConf.merge()`, `OmegaConf.to_object()`, `OmegaConf.structured()`,
`OmegaConf.unsafe_merge()`. Every interaction with data requires thinking
about whether you have a DictConfig or a dict, whether you need to merge
or create, whether to use structured or unstructured.

OmegaConf is a config library being used as a data model. The result is
defensive code everywhere:

```python
if isinstance(self.params, DictConfig):
    self.params = OmegaConf.to_container(self.params)
```

### 5. The "note to self" problem

Line 1157 of recipe.py:

```python
## OMS: note to self, I had this here but not sure why.
## Seems like a no-op. Something with logname fiddling.
## Leave as a puzzle to future self for a bit.
```

When the primary author doesn't understand why code exists, and leaves it
in as a "puzzle to future self," that's a maintenance red flag. This is
not an isolated case — there are commented-out validation blocks throughout
recipe.py (lines 162-169, 770-776) left in because nobody is confident
they can be removed.

## What Should Have Been Done Differently

### 1. Use Python, not YAML-with-expressions

The fundamental mistake is encoding control flow in YAML. `assign_based_on`
is a switch statement. `preamble`/`epilogue` are pre/post hooks. `for_loop`
is a for-loop. `{recipe.param}` is variable interpolation. `=formula` is
expression evaluation.

All of these exist in Python already, with better error messages, proper
debugging, and IDE support. A recipe should be a Python script that calls
`stimela.run("wsclean", ms="obs.ms", size=4096)`, not a YAML file that
reimplements Python poorly.

Nextflow, Snakemake, and Prefect all learned this lesson. Stimela is still
learning it.

### 2. Keep the parameter model simple

Parameters go IN to a step and come OUT. That's it. The current system has:
- inputs, outputs, named outputs, implicit outputs
- aliases (one-to-one, one-to-many, with wildcards)
- nom_de_guerre (parameter renaming)
- assign (direct variable setting)
- assign_based_on (conditional variable setting)
- preamble/epilogue (expression evaluation)
- DeferredAlias (placeholder for unresolved aliases)
- SkippedOutput (placeholder for skipped step outputs)
- UNSET, Unresolved, Placeholder (three different "not set yet" states)

**Three different "not set yet" states.** That's the tell.

### 3. Don't build a custom expression evaluator

`scabha/evaluator.py` and `scabha/substitutions.py` implement a custom
expression language. This is always a mistake in a domain tool. Use Jinja2
if you need templating. Use Python if you need expressions. Don't build
your own.

### 4. Separate definition from execution

`Recipe` defines the workflow AND runs it. `Step` defines the step AND
runs it. These should be separate concerns. A recipe definition should be
a pure data structure. Execution should be a function that takes a recipe
and runs it. This would make testing, serialization, and reasoning about
the system vastly easier.

## The Bus Factor

Smirnov has written 147 of the 346 commits since 2023 — 42%. He is the
primary author of `recipe.py` (21 of 42 commits). He is the primary filer
of open issues (32 of 68). He leaves himself notes in the code. The
commented-out validation blocks are his. The `assign_based_on` feature is
his. The `nom_de_guerre` naming is his (literally French for "war name").

This is a single-brain codebase wearing a multi-contributor costume. When
one person drives both the feature requests AND the implementation, there
is no check on feature creep. Every itch gets scratched. Every edge case
gets a new YAML keyword. The result is a system that the primary author
can navigate but others struggle with — as evidenced by the issue tracker,
where JSKenyon (the other major contributor, 141 commits) files bugs about
"cryptic errors," "mysterious messages," "silent acceptance," and "odd
behaviour."

## What To Do About It

### Short term (can do now)

1. **Delete the dead code.** docker.py, podman.py, 7 vestigial commands,
   batch.py. ~500 lines. Zero risk.
2. **Fix the 3 confirmed bugs.** Mutable default, emoji no-op, double
   os.path. One-line fixes each.
3. **Close the 12 stale issues.** Stop carrying 4-year-old enhancement
   requests that nobody will implement.

### Medium term (next release)

4. **Freeze the YAML feature set.** No more keywords. No more YAML-encoded
   control flow. If a user needs `assign_based_on`, they can write a Python
   recipe.
5. **Add a Python recipe API.** Let users write `stimela.run()` calls in
   Python instead of YAML. This doesn't replace YAML recipes — it provides
   an escape hatch for complex logic.
6. **Define a Backend protocol.** 20 lines of `typing.Protocol`. Makes the
   contract explicit.
7. **Split Recipe into definition and execution.** Even just extracting
   `_run` and `_iterate_loop_worker` into a `RecipeRunner` would help.

### Long term (if this project wants to survive)

8. **Deprecate the custom expression evaluator.** Replace `{recipe.param}`
   and `=formula` with Jinja2 or f-string-like syntax with well-defined
   semantics.
9. **Simplify the parameter model.** Three "not set yet" states is two too
   many. Nom_de_guerre should be replaced by proper aliases.
   `assign_based_on` should be deprecated.
10. **Write real tests.** The test suite is thin and most critical paths
    (alias propagation, for-loop scatter, backend dispatch) are untested.
    The 4 confirmed bugs are evidence that this code doesn't get exercised
    by tests.
