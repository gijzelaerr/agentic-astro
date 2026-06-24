# Stimela Deep Analysis

Analysis conducted 2026-06-24 by Claude for the agentic-astro workshop.
Target: https://github.com/caracal-pipeline/stimela (v2.2.0rc1, 14.5k lines Python)

## 1. Executive Summary

Stimela is a capable workflow management framework for radio interferometry that
has evolved significantly from its container-centric origins toward a
general-purpose recipe execution engine. The core recipe/step/cab architecture
is sound and actively maintained, but the codebase carries substantial dead
weight from abandoned backends (Docker, Podman), vestigial CLI commands, and
copy-paste duplication that inflates maintenance burden. The issue tracker is
manageable (68 open) but contains ~12 issues that should be closed immediately
as stale or resolved, freeing attention for the ~20 genuinely high-priority
items spanning correctness bugs, reproducibility features, and ecosystem
alignment (Singularity-to-Apptainer). The project would benefit most from a
focused cleanup sprint followed by investment in versioning/caching
infrastructure.

---

## 2. Architecture Assessment

### What Is Clean

- **Recipe/Step/Cab layering**: The conceptual separation between recipes
  (workflow graphs), steps (execution units), and cabs (command definitions) is
  well-designed. Cabs define *what* to run, flavours define *how* to construct
  the command line, and backends define *where* to execute. This orthogonality
  is the project's strongest architectural property.
- **Wrangler system**: Regex-triggered stdout processors are a pragmatic,
  extensible solution for dealing with heterogeneous tool output. The class
  hierarchy (Replace, Suppress, ChangeSeverity, DeclareError, ParseOutput) is
  clean and each wrangler has a single responsibility.
- **OmegaConf-based configuration**: Using structured dataclasses with OmegaConf
  is idiomatic and provides validation, interpolation, and merge semantics for
  free.
- **Rich-based display/logging**: The live display with per-backend style
  variants and the FunkyMessage dual-representation logging are well-conceived.

### What Is Tangled

- **`Recipe` is a god class** (1476 lines, 8+ responsibilities): finalization,
  alias management, prevalidation, assignment propagation, for-loop
  orchestration, DAG construction, step restriction, logging, and execution are
  all in one class. Key methods exceed 130 lines with 5+ nesting levels
  (`_iterate_loop_worker`, `prevalidate`, `update_assignments`).
- **Backend interface is implicit**: No ABC or protocol enforces the expected
  module-level functions (`is_available`, `get_status`, `run`, `build`, `init`,
  `close`, `cleanup`). `_call_backends` and `BackendRunner` use `getattr`
  dispatch, which means a new backend can silently lack required functions until
  runtime.
- **Config classes defined inside `load_config()`**: `StimelaConfig` and
  `StimelaLibrary` are local classes assigned to globals, preventing
  type-checking, IDE support, and clean imports.
- **Dual xrun implementations**: `xrun_poll` (synchronous) and `xrun_asyncio`
  coexist with duplicated command-line construction logic. The relationship
  between them is unclear without reading both files.

### What Should Change

1. Split `Recipe` into at minimum: `RecipeDefinition` (schema, aliases,
   assignments), `RecipeValidator` (prevalidation, propagation), and
   `RecipeRunner` (execution, for-loop orchestration).
2. Define a `Backend` protocol or ABC with required methods, and have each
   backend module implement it explicitly.
3. Move `StimelaConfig`/`StimelaLibrary` to module-level definitions.
4. Consolidate `xrun_poll` and `xrun_asyncio` to share command-line
   construction and dispatch logic, with one clear entry point.

---

## 3. Code Quality

### Complexity Hotspots

| File | Lines | Issue |
|------|-------|-------|
| `kitchen/recipe.py` | 1476 | God class with 8+ responsibilities, methods >130 lines |
| `commands/run.py` | ~730 | File resolution, loading, validation, and execution mixed |
| `kitchen/__init__.py` | ~303 | Three near-identical 65-line functions |
| `recipe.py:_iterate_loop_worker` | 150 | 5+ indentation levels, hard to follow |
| `backends/kube/` | ~1800 | Sophisticated but complex; debug flags and commented-out code |

### Confirmed Bugs

| Location | Bug |
|----------|-----|
| `kitchen/recipe.py:196` | `flatten_dict(input_dict, output_dict={})` — mutable default argument persists across calls |
| `stimelogging.py:49-50` | `FunkyMessage.__init__` sets `self.funky` in the `escape_emojis` branch, then unconditionally overwrites it on line 50, making emoji escaping a no-op |
| `config.py:76` | `os.path.os.path.expanduser` — double `os.path` reference (happens to work but is wrong) |

*Note: An earlier analysis claimed a `"weakly_disbled"` typo in `kitchen/__init__.py` — this was verified to NOT exist. The string is not present in the codebase.*

### Dead Code Inventory

| Item | Lines | Status |
|------|-------|--------|
| `backends/docker.py` | 33 | Checks for docker binary but has no `run()` function — unusable |
| `backends/podman.py` | 256 | `is_available()` hard-returns `False`, uses removed `StimelaLogger` |
| `commands/cabs.py` | ~50 | Body is `pass`, uses old argparse API, not registered |
| `commands/kill.py` | ~30 | Body is `pass`, uses old argparse API, not registered |
| `commands/ps.py` | ~30 | Body is `pass`, uses old argparse API, not registered |
| `commands/pull.py` | ~30 | Body is `pass`, uses old argparse API, not registered |
| `commands/containers.py` | ~50 | Old argparse API, references removed `StimelaLogger` |
| `commands/images.py` | ~40 | References removed `BACKEND` global, would crash on import |
| `commands/push.py` | ~40 | References removed `BACKEND` global, would crash on import |
| `kitchen/batch.py` | 20 | Slurm `Batch` dataclass never imported anywhere |
| `singularity.py:201-257` | 55 | Commented-out auto-update logic |
| `backends/kube/pod_proxy.py:343-403` | 60 | Commented-out file injection / pre-commands |
| `config.py:137-140` | 4 | Commented-out resolver-disabling block |
| `config.py:192` | 1 | `base_configs = lib_configs = cab_configs = []` always empty |
| `recipe.py` (multiple) | ~25 | Commented-out validation and handling blocks |

### Refactoring Opportunities

- **Deduplicate `apply_step_inclusions/exclusions/unskips`**: Three 65-line
  functions in `kitchen/__init__.py` differ only in the status string. Extract
  a single parameterized function.
- **`Step._instantiated_cabs = {}`**: Class-level mutable dict shared across all
  instances acts as a cache leak across recipe runs. Should be scoped to a run
  context.
- **`build.py` calls `run.callback()` directly**: Couples to Click internals.
  Extract a shared helper.
- **`save_config.py` names its command `config`**: Shadows `stimela.config`
  module import, requiring an awkward rename at the import site.

---

## 4. Issues Triage Summary

68 open issues. Recommended: **20 PRIORITY**, **36 KEEP**, **12 CLOSE**.

### PRIORITY — Fix Soon (~20 issues)

| # | Title | Author | Rationale |
|---|-------|--------|-----------|
| 565 | `(filename.py)function` syntax for dynamic schemas | o-smirnov | Actively needed, milestoned R2.2 |
| 563 | Performance metrics mis-report shared memory | JSKenyon | Correctness bug in resource reporting, PRs ready |
| 548 | Switch from Singularity to Apptainer | SpheMakh | Ecosystem alignment, Singularity naming increasingly stale |
| 530 | Silent acceptance of non-existent parameters | JSKenyon | Dangerous silent failure — users get wrong results |
| 552 | CLI assignment mysterious error on 'none' | JSKenyon | Real UX bug, confusing error message |
| 513 | `+` character in log name | JSKenyon | Bug, labeled bug+question |
| 490 | CLI `foo=bar` only works for proper inputs | o-smirnov | UX limitation, frequently hit |
| 467 | Nested assignments silently ignored | JSKenyon | Bug — silent wrong behavior |
| 462 | Maximum recursion depth exceeded | Athanaseus | Crash bug |
| 433 | Recipe substitution namespace should be scrubbed | JSKenyon | Bug — namespace pollution in sub-recipes |
| 364 | `{}`-substitutions fail on `List[Tuple[float,float]]` | talonmyburgh | Bug in type handling |
| 362 | Assign to an input should be prohibited | o-smirnov | Correctness — allows invalid state |
| 349 | Aliases missing check for inputs/outputs confusion | o-smirnov | Correctness guard missing |
| 317 | Recipe input via assign not propagated to aliases | o-smirnov | Confirmed bug in alias propagation |
| 324 | Missing parameter error for non-required outputs | SpheMakh | Bug — non-required outputs shouldn't error |
| 293 | Nested `=`-formulas not evaluated via `{}`-substitutions | o-smirnov | Bug in formula engine |
| 282 | For-loops and step-level assignments fail prevalidation | JSKenyon | Bug — blocks valid workflows |
| 265 | `{{` escapes don't work for `{}`-substitutions | o-smirnov | Bug in escape mechanism |
| 504 | Kube backend assumes metrics server exists | JSKenyon | Bug — crashes without metrics server |
| 301 | PVC deletion error in kube backend | JSKenyon | Bug in kube cleanup |

### KEEP — Valid, Not Urgent (~36 issues)

| # | Title | Author | Rationale |
|---|-------|--------|-----------|
| 561 | Provide true sandboxed mode | o-smirnov | Valid design discussion, no urgency |
| 551 | Temporary directory binding behaviour | JSKenyon | Valid edge case in Singularity binding |
| 546 | telsim cab issues with `_` parameters | Muphulusi12 | Real compatibility issue, needs investigation |
| 520 | Support `help_panel` for doc output | landmanbester | Nice UX improvement, not urgent |
| 516 | Mistake when tweaking cab triggers odd behaviour | JSKenyon | Real but low-frequency edge case |
| 510 | Backend selection, config and env vars | landmanbester | Design discussion about config hierarchy |
| 508 | Default config overridable by user | o-smirnov | Valid feature request |
| 501 | Parse progress bars from console output | o-smirnov | Nice-to-have enhancement |
| 495 | Add 'checking' status at start of step | o-smirnov | Minor UX improvement |
| 494 | Step-level `log` field | JSKenyon | Enhancement, well-specified |
| 493 | `stimela doc` reports aliased inputs incorrectly | landmanbester | Doc generation bug, not blocking |
| 492 | Make log aggregation on scatter optional | JSKenyon | Valid feature request |
| 491 | `skip_if_outputs` needs conditionals | o-smirnov | Valid enhancement |
| 480 | Stimela `publish` command | JSKenyon | Feature request for package publishing |
| 460 | Cryptic error with alias/step input name collision | JSKenyon | Real error, needs better message |
| 449 | Cannot index n elements from a list | Allycan | Edge case in list indexing |
| 444 | Add aliases, phase out nom-de-guerres | o-smirnov | Design discussion |
| 438 | More elegant boolean flag handling | landmanbester | UX improvement |
| 427 | `stimela clean` command | tmolteno | Enhancement |
| 424 | Set metavar of positionals in clickify | o-smirnov | Minor CLI polish |
| 415 | Check Optional[str] defaults from CLI | o-smirnov | Edge case in type handling |
| 411 | Abbreviate very long inputs in print | o-smirnov | Cosmetic improvement |
| 408 | Strange error for wrong File input type | o-smirnov | Better error message needed |
| 404 | Check UNSET/Unresolved usage in evaluator | o-smirnov | Internal code quality |
| 374 | Version info for cabs and packages | bennahugo | Reproducibility feature |
| 373 | Enforcing version dependence | bennahugo | Reproducibility feature |
| 371 | Deprecation warning mechanism | o-smirnov | Useful for API evolution |
| 369 | Caching output results for reuse | o-smirnov | Performance feature, overlaps with memoization |
| 366 | Implicitly select single output | o-smirnov | Minor convenience |
| 356 | Parameter scope concept | tmolteno | Design discussion |
| 334 | Env vars when invoking Singularity | landmanbester | Valid container feature |
| 332 | Expose recipe/package paths | JSKenyon | Feature request |
| 331 | Step-level loops | JSKenyon | Feature request |
| 330 | Non-str choices in clickify | landmanbester | Edge case |
| 313 | "deprecated" property for cab definition | o-smirnov | Pairs with #371 |
| 307 | Recipe result message string | o-smirnov | UX enhancement |
| 306 | Version specifiers for schemas | o-smirnov | Reproducibility feature |
| 303 | Single style for cultcargo cab references | sjperkins | Convention cleanup |
| 297 | Post-init option for container init | JSKenyon | Feature request |
| 290 | `remove_on_error` option for outputs | o-smirnov | Cleanup feature |

### CLOSE — Stale or Resolved (~12 issues)

| # | Title | Author | Rationale |
|---|-------|--------|-----------|
| 289 | Wildcard specifiers in `_include` | o-smirnov | Already labeled `wontfix` by maintainer |
| 184 | Cleanup code for daskjob/daskworkergroup | o-smirnov | 2.5+ years old, no progress, kube-specific |
| 178 | Auto-cleanup inactive temp storage | o-smirnov | 2.5+ years old, no progress |
| 177 | Caching non-File type results | o-smirnov | 2.5+ years old, no progress, overlaps #369 |
| 127 | Gentle Ctrl+C interrupt | o-smirnov | 3.5+ years old, no traction |
| 115 | Add pip option to cabs | o-smirnov | 3.5+ years old, no traction |
| 87 | Improve test coverage | landmanbester | Too vague, 3.5+ years old |
| 36 | Explore nix as runner | SpheMakh | 4+ years old, purely exploratory, no activity |
| 12 | Add docker support | SpheMakh | 4+ years old, docker.py is dead code |
| 547 | Lingering Divorce Trauma? | kwazzi-jack | Trivial check — verify and close |
| 372 | Cultcargo integration docs | bennahugo | Documentation-only, stale 1+ year |

---

## 5. PR Recommendations

| PR | Title | Author | Action | Rationale |
|----|-------|--------|--------|-----------|
| #564 | Check file permissions for writable inputs | o-smirnov | **MERGE** | Clean, focused fix for #439. Adds permission check before step runs. |
| #562 | Shared memory counting (alternative to #560) | JSKenyon | **MERGE** | Better approach — uses `/proc/pid/smaps` for accurate shared memory. Addresses #563. |
| #560 | Avoid counting shared memory multiple times | adevress | **CLOSE** | Superseded by #562 which takes a more thorough approach. |

**Merge order**: #564 first (independent), then #562 (closes #563), then close #560.

---

## 6. Top 10 Recommendations

### 1. Delete dead code NOW
Remove `docker.py`, `podman.py`, and 7 vestigial command files (`cabs`, `kill`,
`ps`, `pull`, `containers`, `images`, `push`), plus `kitchen/batch.py`. ~500
lines of code that can never execute. Zero risk, immediate clarity.

### 2. Fix the 4 confirmed bugs
The mutable default in `flatten_dict`, FunkyMessage emoji no-op, and double
`os.path`. All are one-line fixes with real impact.

### 3. Merge PR #564 and #562
Both are clean, focused fixes for real issues. Close #560 as superseded.

### 4. Close 12 stale issues
Reduces noise and focuses maintainer attention on what matters.

### 5. Rename Singularity to Apptainer (#548)
Singularity is increasingly stale branding. Mostly a module + config key rename
with backward-compat aliases.

### 6. Fix silent failure modes
#530 (non-existent params accepted silently) and #467 (nested assignments
silently ignored) are the most dangerous class of bugs. Users get wrong results
with no warning.

### 7. Define a Backend protocol
Add a `typing.Protocol` or ABC for backends. Current `getattr` dispatch hides
missing methods until runtime. Small, high-leverage change.

### 8. Deduplicate `kitchen/__init__.py`
The three 65-line copy-paste functions should be one parameterized function.
Easy refactor, reduces maintenance surface.

### 9. Split Recipe class
The 1476-line god class is the biggest long-term maintainability risk. Even
splitting validation from execution would be a significant improvement.

### 10. Fix the formula/substitution bug cluster
Issues #293, #265, #282, #364 all relate to the substitution engine. Fix them
together as a focused effort rather than one-off patches.

---

## 7. What Should Be Removed

### Backends to Delete
- **`backends/docker.py`** — checks for docker binary but has no `run()`
  function. Unusable as a backend.
- **`backends/podman.py`** — `is_available()` returns `False`. References
  `StimelaLogger` which was removed. Would crash if enabled.

### CLI Commands to Delete
- **`commands/cabs.py`** — body is `pass`, old argparse API
- **`commands/kill.py`** — body is `pass`, old argparse API
- **`commands/ps.py`** — body is `pass`, old argparse API
- **`commands/pull.py`** — body is `pass`, old argparse API
- **`commands/containers.py`** — old argparse API, references removed logger
- **`commands/images.py`** — references removed `BACKEND` global, would crash
- **`commands/push.py`** — references removed `BACKEND` global, would crash

### Other Dead Code
- **`kitchen/batch.py`** — Slurm Batch dataclass, never imported
- **Commented-out blocks**: singularity.py (55 lines), pod_proxy.py (60 lines),
  config.py (4 lines), recipe.py (25 lines)
- **`config.py:192`** — `base_configs = lib_configs = cab_configs = []` always
  empty, loop logic is dead weight
