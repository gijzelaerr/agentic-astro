# Stimela Architecture: Analysis & Decision Document

**Date**: 2026-06-25
**Input**: ANALYSIS.md, CRITIQUE.md (stimela), CRITIQUE.md (scabha), independent codebase verification
**Purpose**: Synthesize findings into actionable decisions about Stimela's future

---

## Verified Findings

Every major claim from the input analyses was independently verified against the codebase. Key numbers:

| Claim | Reported | Verified |
|-------|----------|----------|
| Recipe class lines | 1476 | 1476 |
| Recipe methods | 31 | 25 (31 included properties/dunders) |
| Recipe responsibilities | 8+ | 8 distinct groups confirmed |
| Evaluator built-in functions | 29 | 29 exactly |
| `isinstance(*, Unresolved)` in evaluator | 19 | **26** (undercount) |
| Sentinel types | 5-6 | 6 confirmed |
| Parameter fields (Parameter + ParameterPolicies) | 39 | **42** (undercount) |
| Dead code lines | ~500 | ~500+ (schedulers/ also dead) |
| Backend Protocol/ABC | none | none confirmed |
| `_iterate_loop_worker` 9-tuple return | claimed | confirmed exactly |

Additional findings:
- `DeferredAlias` has **zero isinstance checks** anywhere — it's created but never discriminated on
- `schedulers/slurm.py` imports `batch.py` but is itself never imported — the dead code footprint is larger than reported
- The evaluator and substitution system are **bidirectionally coupled** with shared namespace resolution and mutual callbacks

---

## The Four Questions

### Q1: Do we commit to a Python-first recipe syntax (Stimela3)?

**Recommendation: Yes.**

The evidence is overwhelming:

1. **The YAML-as-language problem is the root cause of the bug cluster.** Issues #293, #265, #282, #364 all stem from under-specified semantics of a home-grown expression language. These bugs cannot be fixed well — only worked around — because the semantics weren't designed, they accreted.

2. **The evaluator is larger than the validator.** A "parameter validation tool" where the expression evaluator (977 lines) is bigger than the validator (346 lines) has inverted priorities. The tail is wagging the dog.

3. **The complexity is self-generating.** All 3 open scabha issues are about making the YAML config inheritance system more flexible. The `assign_based_on` feature alone accounts for ~50 lines of assignment logic and 18 references. Every YAML-encoded control-flow feature creates demand for the next one.

4. **The competitive landscape has converged.** Nextflow DSL2, Snakemake, and Prefect all use Python/Groovy for control flow with declarative annotations for metadata. Stimela is the outlier.

5. **The user base is already writing Python.** Oleg's own `preamble`/`epilogue` expressions are Python encoded as YAML strings. Users who need conditional logic are already escaping into `=IF(VALID(...), ...)` formulas — Python with worse error messages.

**What Python-first means concretely:**
- Recipes are Python functions decorated with `@stimela.recipe`
- Steps are calls to `stimela.run("cab_name", param=value)`
- Control flow (if/for/switch) is native Python
- Parameter schemas use type annotations or a lightweight decorator
- Container/backend selection remains declarative (decorator or config)
- YAML stays for cab definitions (tool metadata) — that's genuinely declarative data

**What Python-first does NOT mean:**
- It does not mean caracal-style imperative spaghetti. The decorator pattern constrains structure.
- It does not mean losing readability. A well-designed API can be more readable than YAML with `assign_based_on` and `=IF(VALID(...))`.
- It does not mean rewriting everything at once. See Q2.

### Q2: What's the migration path?

**Recommendation: Dual syntax, YAML not deprecated but repositioned.**

```
v2.2  (now)       Cleanup release — dead code removal, confirmed bug fixes, Backend Protocol
v2.3  (3 months)  Python recipe API added alongside YAML. Both work. New features go to Python API.
v3.0  (9 months)  `stimela eject recipe.yml` transpiler: YAML → Python code generator.
                   YAML recipes remain supported as a convenience layer for simple pipelines.
```

**Revised direction (per group discussion):**
- YAML recipes are NOT deprecated — they remain the simple authoring format for linear pipelines
- Python is the *runtime foundation* and the *power-user format*
- When a YAML recipe outgrows YAML's expressiveness, `stimela eject` generates editable Python
- The evaluator/substitution engine moves conceptually from "runtime" to "transpiler"
- Both paths converge at the cab registry — everything below that is shared
- See `IMPLEMENTATION-PLAN.md` for the full phased plan and API design

**Why keep YAML:**
- Most astronomers write simple linear pipelines — YAML is genuinely lower-barrier for those
- Existing recipes and cultcargo are a significant body of working YAML
- YAML-as-language is only a problem when people need control flow; simple pipelines don't
- The transpiler gives an escape hatch when YAML gets complex

**Why Python as the foundation:**
- The runtime only needs to understand one execution model
- Evaluator bugs in YAML recipes become transpiler bugs — inspectable and fixable in the generated Python
- New features (caching, parallel, DAG) only need one implementation
- IDE support, debugging, proper error messages come for free

### Q3: What happens to scabha?

**Recommendation: Scabha stays for YAML support. Its evaluator becomes the transpiler's engine. Useful parts are shared with the Python API.**

Scabha's role changes from "runtime expression engine" to "YAML compatibility and transpilation layer":

- **Pydantic type coercion** (validate.py) — shared by both paths, stays
- **Click CLI generation** (schema_utils.py `clickify_parameters`) — shared, stays
- **Config dependency tracking** (configuratt/deps.py) — shared, stays
- **Base types** (File, Directory, URI, MS) — shared, stays
- **Expression evaluator** (evaluator.py, 977 lines) — used by YAML path and transpiler, NOT by Python recipes
- **Substitution engine** (substitutions.py, 468 lines) — same: YAML path only

**The "divorce" paradox still applies:** Scabha contains stimela-specific types and the divorce was never completed. But rather than killing scabha now, we let it naturally shrink in importance as Python recipes become the primary path. The evaluator and sentinel hierarchy become implementation details of the YAML compatibility layer, not core infrastructure.

**Timeline:**
- v2.2: No scabha changes
- v2.3: Python API bypasses evaluator/substitution — uses pydantic directly
- v3.0: Evaluator powers the `stimela eject` transpiler
- Long term: If YAML recipes are eventually removed, scabha shrinks to just types + validation

### Q4: What's the timeline?

**Recommendation: Three phases over 18 months.**

#### Phase 1: Cleanup (v2.2) — Now to 3 months

Zero-risk, high-value work that doesn't change any user-facing behavior:

| Task | Effort | Impact |
|------|--------|--------|
| Delete dead code (docker.py, podman.py, 7 commands, batch.py, schedulers/) | 1 day | -500+ lines, clarity |
| Fix 3 confirmed bugs (mutable default, emoji no-op, double os.path) | 1 hour | Correctness |
| Define Backend Protocol | 1 day | Contract enforcement |
| Deduplicate `kitchen/__init__.py` (3 copy-paste functions) | 1 day | Maintainability |
| Close 12 stale issues | 1 day | Focus |
| Merge PRs #564, #562; close #560 | 1 day | Unblock contributors |
| Rename Singularity to Apptainer (#548) | 2-3 days | Ecosystem alignment |

#### Phase 2: Python API (v2.3) — 3 to 9 months

| Task | Effort | Impact |
|------|--------|--------|
| Design Python recipe decorator API | 2-3 weeks | Foundation for Stimela3 |
| Implement `@stimela.recipe` and `stimela.run()` | 4-6 weeks | Dual syntax |
| Split Recipe class (definition+validation vs execution) | 2-3 weeks | Maintainability |
| Collapse sentinel types to 2 | 1-2 weeks | Simplicity |
| Fix silent failure modes (#530, #467) | 1-2 weeks | Correctness |
| Write `stimela convert` YAML→Python tool | 2-3 weeks | Migration enabler |

#### Phase 3: Transition (v3.0) — 9 to 18 months

| Task | Effort | Impact |
|------|--------|--------|
| Deprecate YAML recipe syntax | 1 week | Signal |
| Merge scabha useful parts into stimela | 2-3 weeks | Simplification |
| Remove expression evaluator | 1-2 weeks | -977 lines |
| Simplify parameter model (42 → ~8 fields) | 2-3 weeks | Clarity |
| Remove YAML recipe support | 1 week | Finality |

---

## Architecture Decisions Record

### ADR-1: Python-first recipes

**Status**: Proposed
**Decision**: Stimela3 recipes are Python functions with decorators. YAML recipes are deprecated in v3.0, removed in v3.1.
**Rationale**: The YAML-as-language anti-pattern is the root cause of the substitution bug cluster and the primary driver of codebase complexity. Python provides better control flow, error messages, debugging, and IDE support.
**Consequences**: Existing YAML recipes need migration. A converter tool and 12-month deprecation window mitigate this.

### ADR-2: Scabha reabsorption

**Status**: Proposed
**Decision**: Scabha's useful components (type coercion, CLI generation, config deps) merge into stimela. The expression evaluator and sentinel hierarchy are removed.
**Rationale**: Scabha's independence is a fiction — it contains stimela-specific types and the divorce was never completed. Its expression evaluator exists to work around YAML's lack of expressions; Python recipes eliminate this need.
**Consequences**: Scabha PyPI package becomes a compatibility shim, then is archived.

### ADR-3: Backend Protocol

**Status**: Proposed
**Decision**: Define a `typing.Protocol` for backends with required methods (`is_available`, `get_status`, `is_remote`, `run`) and optional methods (`init`, `close`, `cleanup`, `build`).
**Rationale**: Current `getattr` dispatch hides missing methods until runtime. Docker and podman backends prove this — they're importable but cannot execute. A Protocol makes the contract explicit and enables type checking.
**Consequences**: Existing backends (native, singularity, kube) need trivial adaptation. Dead backends (docker, podman) are deleted rather than adapted.

### ADR-4: Recipe class decomposition

**Status**: Proposed
**Decision**: Split Recipe (1476 lines, 8 responsibilities) into RecipeDefinition (schema, aliases, assignments) and RecipeRunner (execution, for-loop orchestration). Validation logic stays with definition since it mutates definition state.
**Rationale**: The god class is the biggest long-term maintainability risk. The natural split boundary is between state-building (finalization, validation) and state-consuming (execution).
**Consequences**: Internal refactor. No user-facing API change. The 9-tuple return from `_iterate_loop_worker` should become a dataclass.

### ADR-5: Sentinel type collapse

**Status**: Proposed
**Decision**: Collapse 6 sentinel types to 2: `Missing` (value not yet provided) and `Failed` (resolution attempted and failed, carries error context).
**Rationale**: `DeferredAlias` has zero isinstance checks — it's never discriminated on. `Placeholder` is only checked via "is Unresolved but not Placeholder" — that's a flag, not a type. `_UNSET_DEFAULT` is a string workaround for OmegaConf. The 5-way hierarchy forces 40+ isinstance checks across the codebase.
**Consequences**: Requires careful migration of the 40+ isinstance checks. Some checks can be eliminated entirely; others become simpler two-way branches.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Python API less readable than YAML for simple recipes | Medium | High | Acid test against tron-pfb.yml before committing. Oleg's explicit concern. |
| Migration burden alienates existing users | Medium | High | Converter tool + 12-month window + YAML cab definitions stay |
| Refactoring introduces regressions | Medium | Medium | Phase 1 cleanup first (adds no features). Test coverage improvement before Phase 2. |
| Scabha reabsorption creates merge conflicts | Low | Medium | Do it in one focused PR, not incrementally |
| Timeline slips | High | Low | Each phase delivers standalone value. v2.2 is useful even if v3.0 never ships. |

---

## Open Questions for the Group

1. **The readability acid test**: The sprint plan identifies `tron-pfb.yml` as the acid test. Before committing to ADR-1, someone should sketch what that recipe looks like in Python. If it's not MORE readable than the YAML version, the premise fails. This is Item 3 in the sprint plan.

2. **cultcargo migration**: How many YAML recipes exist in cultcargo? Is the converter tool sufficient, or do some recipes need hand-migration?

3. **Who maintains the Python API?** The bus factor concern from the critique applies here too. If Oleg designs the Python API alone, we get the same single-brain problem in a new syntax.

4. **Backwards compatibility for cab definitions**: Cab definitions (tool metadata) should stay YAML — they're genuinely declarative. But should the 42-field parameter schema be simplified in v3.0, or kept for cab compatibility?

5. **The caracal anti-pattern**: Oleg explicitly warns that the last Python-based workflow (caracal) devolved into messy imperative code. What guardrails prevent this from happening again? The decorator pattern constrains structure, but how strictly?
