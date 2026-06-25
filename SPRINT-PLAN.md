# Stimela Sprint Plan — 2026-06-25

Three work items for today. Items 1 and 2 can run in parallel sessions.
Item 3 depends on the direction established by item 1.

---

## Item 1: Architecture Analysis & Direction

**Goal**: Synthesize yesterday's analysis into actionable decisions about Stimela's future.

**Input documents** (already written):
- `stimela-analysis/ANALYSIS.md` — deep analysis of stimela codebase (14.5k lines, 68 open issues, 3 PRs)
- `stimela-analysis/CRITIQUE.md` — opinionated assessment of design decisions
- `scabha-analysis/CRITIQUE.md` — assessment of scabha (5.6k lines, expression evaluator, sentinel types)

**Key findings from yesterday**:

1. **Recipe is a god class** — 1476 lines, 31 methods, 8+ responsibilities. Longest method is 187 lines. Handles finalization, alias management, prevalidation, assignment propagation, for-loop orchestration, DAG construction, step restriction, logging, and execution.

2. **YAML-as-language problem** — Stimela reimplements control flow (assign_based_on = switch, for_loop = for, preamble/epilogue = pre/post hooks, {recipe.param} = interpolation, =formula = eval) inside YAML. This is the root cause of the 4+ substitution bugs (#293, #265, #282, #364).

3. **Scabha's expression evaluator** — 977 lines, 29 built-in functions, pyparsing grammar. This is a Turing-incomplete scripting language. Should be replaced by Python or Jinja2.

4. **Six sentinel types for "not set"** — UNSET, Unresolved, Placeholder, SkippedOutput, DeferredAlias, plus a string sentinel _UNSET_DEFAULT. Should be at most two.

5. **39 parameter fields** — 25 in Parameter + 14 in ParameterPolicies. Most users need 4 (dtype, default, required, info). The rest are compatibility shims for specific radio astronomy tools.

6. **Dead code** — ~500 lines of never-executable code: docker.py, podman.py, 7 vestigial command files, batch.py, commented-out blocks.

7. **No backend protocol** — Backends are modules with functions discovered via getattr. No ABC or Protocol. Docker and Podman prove this — they're importable but can never execute.

8. **The "divorce" is incomplete** — Scabha is supposed to be independent but contains stimela-specific types (StimelaPendingDeprecationWarning, nom_de_guerre, ParameterPolicies, MS type).

9. **3 confirmed bugs** — Mutable default in flatten_dict, FunkyMessage emoji no-op, double os.path reference.

**Decisions to make**:

- Do we commit to a Python-first recipe syntax (Stimela3)?
- If yes, what's the migration path? (Big bang vs. dual syntax period?)
- What happens to scabha? (Merge back into stimela? Kill the expression evaluator? Keep as-is?)
- What's the timeline? (Stimela 2.2 cleanup release → 2.3 with Python recipes → 3.0 full transition?)

**Deliverable**: A written decision document capturing the group's answers to these questions.

---

## Item 2: Issue Triage (Bugfix Sprint)

**Goal**: Go through all 68 open issues per the methodology in Discussion #566.

**Sprint methodology** (from Oleg's Discussion #566):

### Step 1: Categorize unmilestoned issues

For each issue without a milestone, assign one of:
- **sprint** — legit, implementable, fix now
- **death row** — invalid, outdated, already fixed → close
- **pink pony** — too vague/wishy-washy to implement
- **humans help!** — Claude can't decide, needs human input

Add a comment explaining the decision.

### Step 2: For sprint-labeled issues, decide approach

- **Fix without rearchitecting + has test coverage** → implement on `issue-XYZ` branch, PR
- **Fix without rearchitecting + no test coverage** → tests first on `issue-XYZ-tests` branch + PR, then fix on `issue-XYZ` branch + PR
- **Fix requires some rearchitecting** → propose plan on issue, label "humans help!"
- **Fix requires major rearchitecture** → explain on issue, label "humans help!"

### Pre-existing triage from yesterday's analysis

**Recommended CLOSE (~12 issues):**

| #   | Title | Reason |
|-----|-------|--------|
| 289 | Wildcard specifiers in _include | Already labeled wontfix |
| 184 | Cleanup code for daskjob/daskworkergroup | 2.5+ years, no progress |
| 178 | Auto-cleanup inactive temp storage | 2.5+ years, no progress |
| 177 | Caching non-File type results | 2.5+ years, overlaps #369 |
| 127 | Gentle Ctrl+C interrupt | 3.5+ years, no traction |
| 115 | Add pip option to cabs | 3.5+ years, no traction |
| 87  | Improve test coverage | Too vague, 3.5+ years |
| 36  | Explore nix as runner | 4+ years, exploratory |
| 12  | Add docker support | 4+ years, docker.py is dead code |
| 547 | Lingering Divorce Trauma? | Verify and close |
| 372 | Cultcargo integration docs | Stale 1+ year |

**Recommended PRIORITY (~20 issues):**

| #   | Title | Type |
|-----|-------|------|
| 565 | (filename.py)function syntax for dynamic schemas | Feature, milestoned R2.2 |
| 563 | Performance metrics mis-report shared memory | Bug, PR ready |
| 548 | Switch from Singularity to Apptainer | Ecosystem alignment |
| 530 | Silent acceptance of non-existent parameters | Dangerous silent failure |
| 552 | CLI assignment mysterious error on 'none' | UX bug |
| 513 | + character in log name | Bug |
| 490 | CLI foo=bar only works for proper inputs | UX limitation |
| 467 | Nested assignments silently ignored | Silent wrong behavior |
| 462 | Maximum recursion depth exceeded | Crash bug |
| 433 | Recipe substitution namespace should be scrubbed | Namespace pollution |
| 364 | {}-substitutions fail on List[Tuple[float,float]] | Type handling bug |
| 362 | Assign to an input should be prohibited | Correctness |
| 349 | Aliases missing check for inputs/outputs confusion | Correctness |
| 317 | Recipe input via assign not propagated to aliases | Alias propagation bug |
| 324 | Missing parameter error for non-required outputs | Bug |
| 293 | Nested =formulas not evaluated via {}-substitutions | Formula engine bug |
| 282 | For-loops and step-level assignments fail prevalidation | Bug |
| 265 | {{ escapes don't work for {}-substitutions | Escape bug |
| 504 | Kube backend assumes metrics server exists | Bug |
| 301 | PVC deletion error in kube backend | Bug |

**Issues already milestoned (excluded from triage):**
#265, #282, #290, #293, #306, #313 (R2.3), #307 (R2.2), #317 (R2.2.1)

### PRs to act on

| PR  | Title | Action |
|-----|-------|--------|
| #564 | Check file permissions for writable inputs | MERGE |
| #562 | Shared memory counting | MERGE (closes #563) |
| #560 | Avoid counting shared memory multiple times | CLOSE (superseded by #562) |

Merge order: #564 first, then #562, then close #560.

### Issues from Discussion #568 (Oleg's stale audit)

22 unmilestoned issues flagged as stale. Grouped by:
- **A**: Older than 2 years (13 issues: #12, #36, #87, #115, #127, #177, #178, #184, #289, #297, #301, #303, #324)
- **B**: Zero comments, untouched 6+ months (6 issues: #480, #495, #501, #504, #510, #331)
- **C**: Last updated >1 year ago (3 issues: #330, #332, #364)

---

## Item 3: Stimela3 Prototype

**Goal**: Design and demonstrate a Python-decorator-based syntax for Stimela3 recipes.

**Context from Discussion #567**:
Oleg's challenge: "Our robot overlords have made some pretty bold claims about how easy it would be to come up with a Python decorator-based syntax to replace stimela's YAML recipes."

**Critical constraint** (Oleg's caveat): The last time they used Python-based workflows (caracal), it turned into messy imperative code. The YAML complexity exists for a reason — concise recipe readability. The prototype has to be MORE readable than YAML, not less.

**Deliverables**:
1. Prototype syntax specification
2. Tutorial document
3. Rewrite of Stimela2 paper code examples in new syntax
4. Rewrite of `tron-pfb.yml` from https://github.com/ratt-ru/breifast — the acid test

**Design principles** (from the analysis):
- Parameters go IN and come OUT. Keep the model simple.
- Use Python for control flow (if/for/switch), not YAML keywords
- Use decorators for metadata (cab definitions, parameter schemas)
- Keep the container/backend abstraction — that's the valuable part
- Substitution = Python f-strings or variables. No custom evaluator.
- Aliases = function arguments. No nom_de_guerre.

**Reference to study**:
- Nextflow DSL2 syntax
- Snakemake rules
- Prefect flows/tasks
- The caracal anti-pattern to avoid: https://github.com/caracal-pipeline/caracal/blob/master/caracal/workers/selfcal_worker.py
- The Stimela2 paper: https://www.sciencedirect.com/science/article/pii/S2213133725000320
- tron-pfb.yml from breifast repo

**Approach**: Start with the tron-pfb.yml recipe (since that's the acid test), sketch what it would look like in Python, iterate on the syntax until it's at least as readable as the YAML version, then generalize into a spec.

---

## Parallelization

- **Session A** (this session): Item 1 — Architecture analysis discussion with the group
- **Session B** (parallel session): Item 2 — Issue triage, following the sprint methodology above
- **Item 3**: After items 1 and 2 converge, either session picks up the prototype work

To start Session B for the issue triage, open a new Claude Code session in the stimela repo and say something like:

> Follow the sprint plan in ~/Github/gijzelaerr/agentic-astro/SPRINT-PLAN.md, Item 2. Triage all open issues per the methodology described there. Start with the "death row" candidates, then work through the priority list.
