# Scabha: A Critical Assessment

Analysis conducted 2026-06-24.
Target: https://github.com/caracal-pipeline/scabha (v2.2.0rc1, 5.6k lines Python)

## What Scabha Is

Scabha is the parameter validation and substitution engine underneath Stimela.
It's supposed to be "an argument parser and validation tool." What it actually
is: **a home-grown programming language with 29 built-in functions, a pyparsing
grammar, and 977 lines of expression evaluator** — accidentally embedded inside
a config library.

## The Evaluator Problem

`evaluator.py` is 977 lines. It is the single largest file in the project.
For a "parameter validation tool," the expression evaluator is bigger than the
validator (346 lines), the schema definition (686 lines), and the substitution
engine (468 lines).

### It's a programming language

The evaluator implements:

**29 built-in functions:**
ERROR, ABORT, LOG, LOG_INFO, LOG_WARNING, LOG_ERROR, LOG_CRITICAL, LIST, LEN,
RANGE, VALID, TRY, MIN, MAX, GETITEM, IS_STR, IS_NUM, CASES, IF, IFSET,
GLOB, EXISTS, DIRNAME, BASENAME, EXTENSION, STRIPEXT, NOSUBST, SORT, RSORT

**All standard operators:**
`+`, `-`, `*`, `/`, `//`, `**`, `<<`, `>>`, `&`, `^`, `|`, `==`, `!=`, `<=`,
`<`, `>=`, `>`, `in`, `not in`, `and`, `or`, `not`, `~`

**Array indexing** via `GetItemHandler`

**Namespace lookups** with wildcards (`fnmatch.filter`)

**String interpolation** via `{recipe.param}` syntax

**A pyparsing grammar** (`construct_parser`, 72 lines) with packrat caching

This is not a validation library. This is a Turing-incomplete scripting
language serialized as YAML strings that start with `=`. The formula
`=IF(VALID(recipe.ms), BASENAME(recipe.ms), "default")` is Python with
worse syntax. And four open bugs in Stimela exist because the semantics
of this language are under-specified.

### Why it exists

The stated purpose: allow YAML recipes to compute derived values. The classic
example: `output_ms: =STRIPEXT(recipe.input_ms) + "_calibrated.ms"`. This
is useful. But the solution scaled from "simple string interpolation" into
a full expression language without anyone noticing they were building one.

The moment you add `IF`, `CASES`, `TRY`, and `LOG` to your expression
evaluator, you are building a programming language. At that point you should
stop and use an actual one.

### What should have been done

Jinja2 for string templating. Python for expressions. Both are battle-tested,
debuggable, and understood by the community. The custom evaluator provides
nothing that `eval()` in a restricted namespace wouldn't, except worse error
messages and 4 open substitution bugs.

## The Sentinel Type Zoo

Scabha defines **4 sentinel classes** for "not set yet":

```python
class Unresolved(object):     # base: "something went wrong during resolution"
class UNSET(Unresolved):      # "value was never provided"
class Placeholder(Unresolved): # "will be set later (e.g., for-loop variable)"
class SkippedOutput(Unresolved): # "output from a skipped step"
```

Stimela adds a 5th: `DeferredAlias(Unresolved)` — "alias not yet resolved."

Five classes to represent the concept of "this doesn't have a value yet."
They propagate through the entire evaluation pipeline, and every function
that touches a value must check `isinstance(value, Unresolved)` before
proceeding. The evaluator alone has **19** `isinstance(*, Unresolved)` checks.

Python already has `None`. If you need to distinguish "not provided" from
"explicitly None," the standard pattern is a sentinel constant:
`_MISSING = object()`. One. Not five.

The irony is that scabha *also* has `_UNSET_DEFAULT = "<UNSET DEFAULT VALUE>"`
in `cargo.py:48` — a string sentinel for OmegaConf contexts where the
dataclass sentinel won't work. So there are actually **six** ways to say
"not set" in this codebase.

## The Parameter Schema

The `Parameter` dataclass has **25 fields**:

```
info, writable, dtype, implicit, tags, required, choices, element_choices,
default, aliases, mkdir, path_policies, remove_if_exists, access_parent_dir,
write_parent_dir, must_exist, skip_freshness_checks, nom_de_guerre, policies,
category, metavar, abbreviation, metadata, suppress_cli_default
```

Three of these (`remove_if_exists`, `access_parent_dir`, `write_parent_dir`)
are deprecated in favour of `path_policies` but still present. `nom_de_guerre`
exists because someone thought "war name" was a clever way to say "CLI alias."
`suppress_cli_default` is a boolean that exists for a single edge case.

Then there's `ParameterPolicies` with another **14 fields**:

```
key_value, positional, positional_head, repeat, prefix, skip, skip_implicits,
disable_substitutions, explicit_true, explicit_false, explicit_flag, is_flag,
split, replace
```

That's **39 fields** across two dataclasses to describe one parameter.
Most users will use `dtype`, `default`, `required`, and `info`. The other
35 fields exist for edge cases in how different radio astronomy tools
interpret command-line arguments.

This is not a general-purpose parameter library. It's a compatibility shim
for the peculiarities of CASA, wsclean, quartical, and a handful of other
tools, encoded into the type system of a "general-purpose" framework.

## validate_parameters: The 268-Line Function

`validate.py:validate_parameters()` is a single 268-line function with
**12 parameters**. It handles:

1. Unknown parameter checking
2. Default value application
3. Substitution evaluation (via the formula engine)
4. Pydantic v2 type coercion
5. File/directory existence checking
6. Directory creation
7. Glob expansion
8. Required parameter enforcement
9. Choice validation
10. Named output handling
11. Implicit parameter resolution
12. UNSET/Unresolved propagation

This is 12 responsibilities in one function. Each responsibility interacts
with the sentinel type zoo. The function has comments like
`# ruff: noqa: E731 - ignore assignment of lambda expressions. TODO(JSKenyon): Fix this.`
at the top of the file.

## The configuratt Module

The config loading system (`scabha.configuratt`) implements its own YAML
inheritance mechanism with `_include`, `_use`, `_scrub`, `_scrub_post`,
`_include_post`, and `_flatten` directives. `core.py:resolve_config_refs()`
is 535 lines of recursive YAML merging.

This is essentially a custom module/import system for YAML. It has:
- File path resolution with `(pkg)module.path` syntax
- Recursion detection via `include_stack`
- Dependency tracking with MD5 checksums and mtimes (`deps.py`)
- A cache layer (`cache.py`)

All of this exists because stimela recipes need to inherit from other
recipes. In Python, you'd call this "importing a module." In scabha, it's
a 535-line recursive YAML merger.

## The Coupling Problem

Scabha is supposed to be an independent library — it has its own repo, its
own version, its own PyPI package. But:

- Its exception hierarchy includes `StimelaPendingDeprecationWarning`
  (cargo.py:36) — a stimela-specific warning in a "general-purpose" library
- The `File`, `Directory`, and `MS` types in `basetypes.py` are radio
  astronomy-specific
- The `nom_de_guerre` concept is a stimela cab concern, not a validation
  concern
- `ParameterPolicies` is entirely about how stimela constructs command lines

Scabha is not a library that stimela uses. Scabha is stimela's guts, ripped
out into a separate repo. The "divorce" (their term — see stimela issue #547
"Lingering Divorce Trauma?") is incomplete. The pyproject.toml even has
`allow-direct-references = true # Remove when divorce is complete` in stimela.

## What's Actually Good

- **Pydantic v2 integration for type coercion** (`validate.py`). Using pydantic
  for parameter type checking is the right call. It's just buried under 250
  lines of other responsibilities.
- **The URI/File/Directory type hierarchy** (`basetypes.py`). Clean, with proper
  `__get_pydantic_core_schema__` hooks and typeguard integration.
- **clickify_parameters** (`schema_utils.py`). Generating Click CLI options from
  parameter schemas is genuinely useful and well-implemented.
- **Config dependency tracking** (`configuratt/deps.py`). Recording file mtimes,
  MD5s, and git info for cache invalidation is proper engineering.

## Issues & PRs

3 open issues, 1 open PR. Small tracker, but telling:

| # | Title | Assessment |
|---|-------|-----------|
| 14 | Support relative references in `_use` | KEEP — valid enhancement for configuratt |
| 13 | Support partial includes | KEEP — reasonable feature request |
| 12 | Support arbitrary placement of `_include`/`_use` | KEEP — addresses a real limitation |
| PR #23 | Version bump | MERGE — trivial |

All 3 issues are about the configuratt module. All 3 are about making the
YAML inheritance system more flexible. This confirms the pattern: the
complexity of the config system generates its own feature requests.

## Top Recommendations

### 1. Stop adding built-in functions to the evaluator

29 is already too many. Every new function is a maintenance commitment and
a potential source of bugs. If users need `SORT`, they need Python.

### 2. Replace the evaluator with Jinja2 or restricted eval

The pyparsing grammar, the 29 built-in functions, the handler classes — all
of this can be replaced by Jinja2 for templates and `ast.literal_eval()` or
a restricted `eval()` for expressions. Better error messages, better
debugging, smaller attack surface.

### 3. Collapse the sentinel types

`UNSET`, `Unresolved`, `Placeholder`, `SkippedOutput`, `DeferredAlias` should
be at most two: a `Missing` sentinel and an `Error` type. The current five-way
hierarchy forces every consumer to think about which flavor of "not set" they
have.

### 4. Split validate_parameters

268 lines and 12 responsibilities. Extract: type coercion (already pydantic),
file checking, glob expansion, and substitution evaluation into separate
functions. The main function becomes a pipeline of these steps.

### 5. Remove deprecated fields from Parameter

`remove_if_exists`, `access_parent_dir`, `write_parent_dir` are deprecated in
favour of `path_policies`. Remove them. `nom_de_guerre` should be removed or
renamed to `cli_name`. 39 fields across two dataclasses is 15 too many.

### 6. Complete the divorce

Remove `StimelaPendingDeprecationWarning` from scabha. Move `nom_de_guerre`,
`ParameterPolicies`, and the `MS` type to stimela where they belong. If scabha
is supposed to be a general-purpose library, it should not contain radio
astronomy types or stimela-specific concepts.

### 7. Consider killing scabha

The useful parts of scabha are: pydantic type coercion, Click CLI generation,
and config loading with dependency tracking. These are ~800 lines of code.
The other 4,800 lines are the expression evaluator, the sentinel hierarchy,
the 39-field parameter schema, and the config inheritance system. If stimela
adopted a Python-first recipe model, most of scabha would be unnecessary.
