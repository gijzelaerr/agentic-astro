# Stimela3 Implementation Plan

**Date**: 2026-06-25
**Companion to**: ARCHITECTURE-DECISIONS.md
**Direction**: Python-first runtime, lightweight own API, future YAML transpiler

---

## Strategic Direction

### What we're building

A Python API for defining and running Stimela recipes. The API replaces YAML recipes as the runtime representation. YAML cab definitions (cultcargo) remain unchanged. A YAML-to-Python transpiler is a future addition, not a blocker.

### What we're NOT building

A new scheduling platform. Stimela's value is the **backend dispatch** (native, Singularity/Apptainer, Kubernetes, SLURM) and the **cab ecosystem** (typed parameter schemas for radio astronomy tools). The orchestration layer is deliberately thin — Python provides control flow, `concurrent.futures` provides parallelism, `graphlib` provides DAG ordering.

### Why not adopt an existing framework

| Framework | What it offers | Why not |
|-----------|---------------|---------|
| **Prefect** | Observability, retries, caching, server UI | Heavy (server + DB). No Singularity. Wraps around our backends, doesn't replace them. |
| **Parsl** | Best SLURM/PBS integration, futures-based DAG | No container support. Futures model is less intuitive for astronomers. Overlaps with but doesn't replace backend dispatch. |
| **Pydra** | Closest match — typed shell commands, Singularity, caching | Alpha quality (v1.0a9), 143 GitHub stars, neuroimaging-specific design. Too risky as a dependency. |
| **Snakemake** | File-centric rules, SLURM, Singularity | Wrong paradigm — rule-based, not step-based. Parameter model doesn't map. |

**Decision**: Build own lightweight API. Study Pydra's `ShellCommandTask` and hash-based caching as design inspiration. Keep the door open for optional Prefect/Parsl integration later (adapter pattern).

---

## The Python API

### Recipe definition

```python
import stimela

@stimela.recipe("Imaging Pipeline", backend="singularity")
def imaging_pipeline(
    ms: stimela.MS,
    output_dir: stimela.Directory = "output",
    image_size: int = 4096,
):
    """Calibrate and image a measurement set."""

    # Steps are just function calls — runs immediately
    cal = stimela.run("quartical",
        ms=ms,
        output_dir=output_dir / "cal",
    )

    # Python for control flow — no assign_based_on, no =IF(VALID(...))
    if image_size > 2048:
        robust = -0.5
    else:
        robust = 0.0

    img = stimela.run("wsclean",
        ms=cal.output_ms,
        size=image_size,
        robust=robust,
        name=output_dir / "image",
    )

    return img
```

### Parallel execution

```python
@stimela.recipe("Multi-field Imaging")
def multi_field(ms_list: list[stimela.MS]):
    # Explicit parallelism via context manager
    with stimela.parallel() as pool:
        results = [pool.run("wsclean", ms=ms, size=4096) for ms in ms_list]

    # Results are resolved here — pool acts as a barrier
    for r in results:
        print(f"Image: {r.output_image}")
```

### Cab definitions (two paths)

**Path 1 — existing YAML (cultcargo stays as-is):**
```yaml
# cultcargo/wsclean.yml
cabs:
  wsclean:
    info: "Wide-field imager"
    command: wsclean
    flavour: wsclean
    inputs:
      ms:
        dtype: MS
        required: true
        info: "Input measurement set"
      size:
        dtype: int
        default: 4096
    outputs:
      image:
        dtype: File
        implicit: true
```

`stimela.run("wsclean", ...)` loads this definition from the cab registry, validates parameters against the schema, constructs the command line, and dispatches to the backend. This is what Stimela already does — the Python API is a new front-end to the same machinery.

**Path 2 — Python-native cabs (new option):**
```python
@stimela.cab(command="wsclean")
def wsclean(
    ms: stimela.MS,
    size: int = 4096,
    robust: float = 0.0,
) -> stimela.outputs(image=stimela.File):
    """Wide-field imager."""
    ...
```

Python cabs use type annotations as the schema. The decorator generates the same internal representation as the YAML loader. Both coexist in the cab registry.

### Backend selection (cascade)

```python
# Global default (config file or environment)
stimela.config.default_backend = "singularity"

# Per-recipe override (decorator)
@stimela.recipe("pipeline", backend="native")
def pipeline(ms): ...

# Per-step override (argument)
stimela.run("wsclean", ms=ms, _backend="kube")
```

Cascade order: step argument > recipe decorator > config default. Same as current Stimela, but explicit Python instead of OmegaConf merge.

### Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Eager vs lazy execution | **Eager** | `stimela.run()` executes immediately. Simpler, Pythonic, debuggable. No futures/promises to reason about. |
| Parallelism | **Explicit** via `stimela.parallel()` | Context manager scopes parallel work. No implicit DAG detection. Astronomers see exactly what runs in parallel. |
| Parameter validation | **Pydantic** | Already proven in scabha. Keep it. |
| CLI generation | **Click** | Already proven. `stimela exec pipeline.py pipeline_name param=value` |
| Return values | **Typed result objects** | `result = stimela.run("wsclean", ...)` returns object with `result.output_image`, `result.success`, etc. |
| Cab registry | **Merged YAML + Python** | YAML cabs (cultcargo) and Python cabs coexist. Same internal representation. |

---

## YAML Transpiler (Future)

Not in scope for v2.3, but the API is designed to make it straightforward. The mapping is direct:

| YAML construct | Python equivalent |
|----------------|-------------------|
| `recipe.inputs` | Function parameters with type annotations |
| `steps.X.cab: Y` | `X = stimela.run("Y", ...)` |
| `=recipe.param` | Python variable reference |
| `=BASENAME(x)` | `pathlib.Path(x).stem` |
| `=IF(cond, a, b)` | `a if cond else b` |
| `assign_based_on` | `if`/`elif` chain |
| `for_loop` | `for` loop |
| `for_loop` + `scatter` | `stimela.parallel()` + `for` loop |
| `aliases` | Function parameters wired to step arguments |

A `stimela eject recipe.yml` command generates readable Python that uses the API above. The generated code should look like something a human would write — not an AST dump.

---

## Implementation Phases

### Phase 1: Foundation (v2.2) — Weeks 1-4

Zero user-facing API changes. Clean the house so Phase 2 builds on solid ground.

| Task | Effort | Dependency |
|------|--------|------------|
| Delete dead code (docker.py, podman.py, 7 commands, batch.py, schedulers/) | 1 day | None |
| Fix 3 confirmed bugs | 1 hour | None |
| Define `Backend` Protocol in `stimela/backends/__init__.py` | 1 day | None |
| Adapt native, singularity, kube backends to Protocol | 2 days | Protocol |
| Deduplicate `kitchen/__init__.py` (3 copy-paste functions → 1) | 1 day | None |
| Merge PRs #564, #562; close #560 | 1 day | None |
| Close 12 stale issues | 1 day | None |
| Rename Singularity → Apptainer (#548) | 2-3 days | None |

**Gate**: All tests pass. No new features, only cleanup.

### Phase 2: Python API (v2.3) — Weeks 5-16

The core work. Build the Python recipe API alongside the existing YAML system. Both work; neither is deprecated.

#### 2a: Core API (weeks 5-8)

| Task | Effort | Detail |
|------|--------|--------|
| `stimela.run()` function | 2 weeks | Load cab from registry, validate params via pydantic, dispatch to backend, return typed result object. This is a clean entry point to the existing `Step.run()` machinery. |
| `@stimela.recipe` decorator | 1 week | Wraps a Python function. Handles backend selection cascade, logging setup, Rich progress display. |
| Typed result objects | 3 days | `RunResult` dataclass with output attributes, success flag, logs. Replaces the implicit output namespace. |
| Cab registry | 1 week | Merge YAML cabs (cultcargo loader, already exists) with Python cabs (`@stimela.cab` decorator). Single lookup: `stimela.cabs["wsclean"]`. |

#### 2b: Parallelism & CLI (weeks 9-12)

| Task | Effort | Detail |
|------|--------|--------|
| `stimela.parallel()` context manager | 1 week | Wraps `concurrent.futures.ProcessPoolExecutor`. Returns futures that resolve on context exit. Respects backend (SLURM jobs fan out via SLURM, not local processes). |
| CLI integration | 1 week | `stimela exec script.py recipe_name param=value` — load a Python module, find the decorated recipe, parse CLI params via Click (reuse clickify_parameters from scabha), run. |
| Parameter file support | 3 days | `stimela exec script.py recipe_name --parameter-file params.yml` — merge YAML params with CLI params. Already partially implemented (#558). |

#### 2c: Testing & docs (weeks 13-16)

| Task | Effort | Detail |
|------|--------|--------|
| Port existing test recipes to Python API | 2 weeks | Prove the API against real recipes. The test suite becomes the specification. |
| Tutorial: "Your first Python recipe" | 3 days | Minimal doc showing the YAML → Python mapping. |
| Acid test: `tron-pfb.yml` in Python | 1 week | The readability test from Discussion #567. Must be at least as readable as the YAML version. |

**Gate**: `tron-pfb.yml` ported and readable. All existing tests pass. New API has test coverage.

### Phase 3: Maturity (v3.0) — Weeks 17-30

Build on the working Python API. Each item is independently valuable.

| Task | Effort | Detail |
|------|--------|--------|
| Hash-based caching (inspired by Pydra) | 2-3 weeks | Hash step inputs → skip if outputs exist and hashes match. Addresses issue #369. |
| `stimela eject recipe.yml` transpiler | 3-4 weeks | YAML → Python code generator. Generates readable code using the Phase 2 API. |
| Recipe class decomposition | 2-3 weeks | Split into definition + runner (ADR-4). Only needed for the YAML runtime path; Python recipes don't use Recipe class. |
| Collapse sentinel types (ADR-5) | 1-2 weeks | 6 → 2. Only affects YAML runtime path and transpiler internals. |
| Simplify parameter model for Python cabs | 2 weeks | 42 → ~8 fields for `@stimela.cab`. YAML cabs keep full schema for backward compat. |
| Optional Prefect/Parsl adapter | 1-2 weeks | `from stimela.integrations.prefect import as_prefect_task` — wrap any cab as a Prefect task. For users who want Prefect's monitoring. Not required. |

---

## Architecture Diagram

```
                    User-facing layer
                    ================
    Python recipes              YAML recipes (existing)
    (@stimela.recipe)           (OmegaConf + evaluator)
         |                            |
         v                            v
    stimela.run()              Recipe._run()
         |                            |
         +------------+---------------+
                      |
                 Cab registry
              (YAML + Python cabs)
                      |
                      v
              Parameter validation
                  (pydantic)
                      |
                      v
              Command construction
              (flavour system)
                      |
                      v
              Backend dispatch
              (Protocol-based)
           /     |      |      \
        native  sing.  kube   slurm
```

The Python API (`stimela.run()`) and the existing YAML runtime (`Recipe._run()`) converge at the cab registry. Everything below that line is shared. This means:
- No duplication of backend logic
- Same parameter validation for both paths
- Cab definitions work identically regardless of recipe format

---

## What This Gets Us

| Problem (from critique) | How it's solved |
|------------------------|-----------------|
| Recipe god class (1476 lines) | Python recipes don't use Recipe class. It stays for YAML compat but stops growing. |
| YAML-as-language (assign_based_on, =IF, for_loop) | Python provides control flow natively. |
| Expression evaluator (977 lines, 4 bugs) | Not used by Python recipes. Bugs only affect YAML path (and eventually, only the transpiler). |
| 6 sentinel types | Not needed in Python API — Python has `None` and exceptions. |
| 42 parameter fields | Python cabs use ~8 fields via type annotations. YAML cabs keep full schema. |
| No backend Protocol | Added in Phase 1. |
| Dead code (~500+ lines) | Deleted in Phase 1. |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Python API isn't readable enough for astronomers | Acid test (tron-pfb.yml) is a Phase 2 gate. Don't ship if it fails. |
| Two runtime paths (Python + YAML) is maintenance burden | They share everything below the cab registry. The fork point is small. |
| Scope creep in the Python API | Freeze scope at: run, recipe, parallel, cab, result. No DAG DSL, no retry decorators, no caching in Phase 2. |
| Breaking cultcargo cab definitions | We don't touch them. The cab registry loads YAML identically to today. |
| YAML transpiler never happens | Fine. Python API stands on its own. The transpiler is a convenience, not a necessity. |

---

## Open Questions

1. **Should `stimela.run()` return a result object or raise on failure?** Recommendation: raise by default (like subprocess.run with check=True), with `stimela.run(..., check=False)` to get a result object with `.success` flag.

2. **How does the parallel context manager interact with SLURM?** When backend=slurm, should `pool.run()` submit SLURM jobs? Or should SLURM parallelism use SLURM array jobs? This needs design input from the SLURM users.

3. **Python cab decorator: how to express outputs?** Options: return type annotation (`-> Outputs(image=File)`), output decorator parameter (`@stimela.cab(outputs={"image": File})`), or separate output schema. Needs API design iteration.

4. **Should the cab registry be global or scoped?** Global is simpler (like current cultcargo). Scoped (per-recipe or per-project) enables overriding cab definitions for testing or specialization.
