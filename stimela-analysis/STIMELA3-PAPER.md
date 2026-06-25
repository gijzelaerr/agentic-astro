# Stimela 3: A Python-native framework for radio interferometry pipelines

**Draft — for Discussion #567**

O.M. Smirnov, G. Molenaar, J.S. Kenyon, L. Bester, et al.

## Abstract

We present Stimela 3, a major revision of the Stimela workflow management framework
for radio interferometry data processing. While Stimela 2 achieved concise pipeline
descriptions through a YAML recipe language with a custom expression evaluator, this
approach led to an accretion of language features — conditional assignments, formula
evaluation, loop constructs, and six sentinel types — that increasingly re-implemented
programming language semantics with under-specified behaviour. Stimela 3 replaces
YAML recipes with a Python-native API where recipes are decorated functions, processing
steps are callable cab objects imported from package registries, and control flow uses
native Python constructs. Cab definitions — the typed parameter schemas for external
tools — remain in YAML and require no migration. The framework retains Stimela 2's
pluggable backend architecture (native, Apptainer, Kubernetes, SLURM) and adds
typed result objects, explicit parallel execution via context managers, and
`Annotated`-based parameter metadata. We demonstrate the API by translating TRON, a
568-line production transient detection pipeline, into 425 lines of Python that are
shorter, statically analysable, and debuggable with standard tools. The Python API
is designed to be transpilable, enabling future compilation to auditable deployment
artifacts for shared HPC environments.

## 1. Introduction

Radio interferometry data reduction pipelines are complex, multi-step workflows that
chain heterogeneous tools — calibrators, imagers, source finders, statistical
analysers — each with distinct command-line interfaces, container requirements, and
resource demands. A pipeline framework must orchestrate these tools with typed parameter
passing, container management, and execution on diverse backends ranging from
single-machine processing to HPC clusters.

Stimela 2 (Smirnov et al. 2025) addressed this with a YAML-based recipe language.
Recipes declared steps, parameters, and data flow in a declarative syntax, while a
custom expression evaluator handled derived values (`=BASENAME(recipe.ms)`),
conditional assignment (`assign_based_on`), and loop constructs (`for_loop` with
`scatter`). This approach achieved its goal: production pipelines like TRON could be
expressed concisely, and the separation of *what* to run (cabs), *how* to run it
(backends), and *in what order* (recipes) was clean.

However, the YAML recipe language grew to re-implement programming language semantics.
The expression evaluator reached 977 lines with 29 built-in functions and a pyparsing
grammar. Six sentinel types (`UNSET`, `Unresolved`, `Placeholder`, `SkippedOutput`,
`DeferredAlias`, plus a string sentinel) encoded "not set yet" states. The parameter
schema grew to 42 fields across two dataclasses. Four open bugs in the substitution
engine (#293, #265, #282, #364) stemmed from under-specified semantics of this
home-grown language.

The core realisation behind Stimela 3 is that the valuable parts of Stimela are not
the expression evaluator or the YAML control flow keywords, but rather:

1. **Cab definitions** — typed parameter schemas for external tools
2. **Backend dispatch** — running the same step on native, Apptainer, Kubernetes, or SLURM
3. **Parameter validation** — pydantic-based type checking of inputs and outputs

These components are preserved. What changes is the recipe layer: instead of a YAML
language that approximates Python, recipes are written in Python itself.

## 2. Architecture

Stimela 3 is structured as three layers:

```
    Recipe layer (Python)         ← NEW: @stimela.recipe, cab()
    ─────────────────────────
    Cab registry (YAML + Python)  ← UNCHANGED: cultcargo, package cabs
    ─────────────────────────
    Backend dispatch (Protocol)   ← IMPROVED: typed Protocol, Apptainer rename
```

### 2.1 Recipe layer

Recipes are Python functions decorated with `@stimela.recipe`. The function signature
defines the recipe's typed inputs and outputs using standard Python type annotations.
Processing steps are invoked by calling imported cab objects directly.

### 2.2 Cab registry

Cab definitions — the typed parameter schemas for external tools — remain in YAML.
The existing cultcargo package and project-specific cab packages (e.g., breifast,
pfb-imaging) require no migration. Each YAML cab definition is auto-exposed as an
importable Python object:

```python
from cultcargo.cabs import wsclean, quartical
from breifast.cabs import flag_cube, extract_lightcurves
```

New cabs may also be defined in Python using the same `@stimela.cab` decorator and
`Annotated` metadata pattern.

### 2.3 Backend dispatch

Backends implement a typed `Protocol` (replacing the previous `getattr`-based module
dispatch) with required methods (`is_available`, `get_status`, `is_remote`, `run`) and
optional methods (`init`, `close`, `cleanup`, `build`). The rename from Singularity to
Apptainer aligns with the upstream project rename. Dead backends (Docker, Podman) are
removed.

## 3. The Python API

### 3.1 Recipes

A recipe is a decorated Python function whose parameters define the recipe's schema:

```python
from typing import Annotated
import stimela
from stimela import Info, Out

@stimela.recipe
def imaging_pipeline(
    ms: Annotated[stimela.MS, Info("input measurement set")],
    image_size: Annotated[int, Info("image size in pixels")] = 4096,
    dir_out: Annotated[stimela.Directory, Out, Info("output directory")],
):
    """Calibrate and image a measurement set."""
    cal = quartical(ms=ms, output_dir=f"{dir_out}/cal")
    wsclean(ms=cal.output_ms, size=image_size, name=f"{dir_out}/image")
```

The `@stimela.recipe` decorator:
- Generates a CLI via Click from the function signature
- Applies the backend selection cascade (step > recipe > config)
- Sets up logging, progress display, and error handling

The `Annotated` type (PEP 593) carries parameter metadata:
- `Info("...")` provides the parameter description (equivalent to YAML's `info:` field)
- `Out` marks a parameter as an output (default is input)
- `stimela.Choices["L", "UHF"]` restricts values to an enumeration

### 3.2 Cab objects

Cabs are imported from their parent packages and called with the `()` operator:

```python
from cultcargo.cabs import wsclean

result = wsclean(ms="obs.ms", size=4096, robust=-0.5)
print(result.restored)  # typed output: path to restored image
```

When a cab is called:
1. Parameters are validated against the cab's schema (pydantic)
2. The command line is constructed according to the cab's flavour
3. The configured backend executes the command
4. Outputs are validated and returned as a typed `RunResult` object

Parameters set to `None` are automatically skipped, replacing the `=IFSET()` pattern
that appeared ~20 times in a typical Stimela 2 recipe.

Cab objects are auto-generated from YAML definitions at package import time. The YAML
cab files in cultcargo are unchanged; a package's `__init__.py` maps hyphenated YAML
names to valid Python identifiers (e.g., `breifast.flag-cube` becomes `flag_cube`).

### 3.3 Control flow

Control flow uses native Python. The table below shows the mapping from Stimela 2
YAML constructs:

| Stimela 2 (YAML) | Stimela 3 (Python) |
|---|---|
| `assign_based_on: band: L: ...` | `if band == "L": ...` |
| `skip: "=recipe.loop == 1"` | `if loop > 1:` |
| `for_loop: {var: x, over: items}` | `for x in items:` |
| `scatter:` under `for_loop` | `with stimela.parallel() as pool:` |
| `=IF(VALID(x), BASENAME(x), "default")` | `Path(x).stem if x else "default"` |
| `=CASES(a, x, b, y, z)` | `if a: ... elif b: ... else: ...` |
| `=STRIPEXT(x) + ".fits"` | `f"{stripext(x)}.fits"` |
| `"{recipe.param}"` | `param` (Python variable) |
| `"{previous.restored}"` | `result.restored` |
| `=IFSET(recipe.x)` | `x` (`None` auto-skipped) |

### 3.4 Sub-recipes

Sub-recipes are function calls. This replaces YAML's nested `recipe:` blocks and
`_use:` references:

```python
@stimela.recipe
def selfcal(ms: Annotated[stimela.MS, Info("measurement set")], n_loops: int = 3):
    """Iterative self-calibration."""
    for i in range(n_loops):
        if i > 0:
            quartical(ms=ms, jones=["G"])
        wsclean(ms=ms, size=4096)


@stimela.recipe
def full_pipeline(ms: Annotated[stimela.MS, Info("input MS")]):
    """Full calibration and imaging pipeline."""
    selfcal(ms=ms, n_loops=3)  # sub-recipe is a function call
```

### 3.5 Parallel execution

The `stimela.parallel()` context manager replaces YAML's `scatter` keyword:

```python
@stimela.recipe
def multi_field(ms_list: Annotated[list[stimela.MS], Info("list of MSs")]):
    """Process multiple fields in parallel."""
    with stimela.parallel() as pool:
        for ms in ms_list:
            pool.call(selfcal, ms=ms, n_loops=3)
```

Steps launched via `pool.run()` (for cabs) or `pool.call()` (for sub-recipes) execute
concurrently. The context manager acts as a barrier — results are available after exit.

### 3.6 Step metadata

Per-step metadata uses underscore-prefixed keyword arguments that are consumed by the
framework rather than passed to the cab:

```python
bdsf_catalog(
    image=deep_image,
    thresh_pix=4,
    _backend="singularity",   # override backend for this step
    _cache="fresh",           # skip if outputs exist and are newer than inputs
    _tags=["lightcurves"],    # tag for selective execution
)
```

- `_backend` overrides the backend for this step (cascade: step > recipe > config)
- `_cache` controls output caching: `"exist"` skips if outputs exist, `"fresh"` skips
  if outputs are newer than inputs (replacing `skip_if_outputs`)
- `_tags` assigns tags for selective step execution via the CLI
  (`stimela exec recipe.py pipeline --tags lightcurves`)

### 3.7 Python cab definitions

New cabs may be defined in Python using the same annotation pattern:

```python
@stimela.cab(command="wsclean")
def wsclean(
    ms: Annotated[stimela.MS, Info("input measurement set")],
    size: Annotated[int, Info("image size in pixels")] = 4096,
    robust: Annotated[float, Info("Briggs robustness")] = 0.0,
    restored: Annotated[stimela.File, Out, Info("restored image")] = None,
    dirty: Annotated[stimela.File, Out, Info("dirty image")] = None,
):
    """Wide-field imager using w-stacking."""
    ...
```

Python and YAML cab definitions coexist in the same registry and are interchangeable
from the recipe's perspective.

## 4. Example: TRON transient detection pipeline

We demonstrate the API with TRON (Transient Radio Observations for Newbies), a
production pipeline for transient detection in radio interferometry data. The original
Stimela 2 YAML recipe is 568 lines; the Stimela 3 Python version is 425 lines.

### 4.1 Main recipe (excerpt)

```python
from breifast.cabs import (
    flag_cube, zarr_to_fits, make_baseline_image,
    consolidate_detections, extract_lightcurves, render_html,
)
from pfb_imaging.cabs import hci
from suricat.recipes import suricat_init

@stimela.recipe
def tron(
    obs: Annotated[str, Info("observation label")],
    ms: Annotated[list[stimela.URI], Info("input measurement set(s)")],
    primary_beam_band: Annotated[
        stimela.Choices["U", "L", "S0", "S1", "S2", "S3", "S4"],
        Info("primary beam band"),
    ],
    deep_image: Annotated[stimela.File, Info("deep image of field")],
    dir_out: Annotated[stimela.Directory, Out, Info("output directory")],
    column: ColumnConfig = field(default_factory=ColumnConfig),
    htc: HtcConfig = field(default_factory=HtcConfig),
    enable_fits_cubes: Annotated[bool, Info("enable FITS cube output")] = True,
    ncpu: Annotated[int | None, Info("number of CPUs")] = None,
    # ... additional parameters ...
):
    """TRON: Transient Radio Observations for Newbies — pfb HCI version."""

    dir_scales = f"{dir_out}/scales"

    # Step 1: High time cadence imaging
    htc_result = hci(
        ms=ms, obs_label=obs,
        data_column=column.data, weight_column=column.weight,
        output_dataset=f"{dir_scales}/raw/cube.raw.zarr",
        integrations_per_image=htc.cadence,
        robustness=htc.robustness, nworkers=ncpu,
        _tags=["lightcurves", "cubes"], _cache="exist",
    )

    # Step 2: Flag excess RMS
    flag_cube(cds=htc_result.output_dataset, _cache="fresh")

    # Step 3-4: Convert to FITS (conditional)
    if enable_fits_cubes:
        zarr_to_fits(
            cds=htc_result.output_dataset,
            out_image=f"{stripext(htc_result.output_dataset)}.fits",
            var="cube", _cache="fresh",
        )

    # Step 5: Primary beams (conditional)
    beams = None
    if primary_beam_band:
        beams = suricat_init(
            dir_out="beam", band=primary_beam_band, _cache="exist",
        )

    # ... 18 more steps follow the same pattern ...
```

Compared to the Stimela 2 YAML:
- The `=IFSET()` pattern (20 occurrences) is replaced by `None` auto-skipping
- The `skip: =not recipe.enable_fits_cubes` expression becomes `if enable_fits_cubes:`
- Step-to-step data flow (`=steps.image-htc.output-dataset`) becomes typed attribute
  access (`htc_result.output_dataset`)
- Grouped parameters (`column.data`, `htc.cadence`) use Python dataclasses

### 4.2 Sub-recipe with for-loop (excerpt)

The breifast multi-timescale analysis sub-recipe demonstrates the for-loop pattern.
The Stimela 2 version uses `for_loop`, `output_elements`, and `=CASES()`:

```python
@stimela.recipe
def tron_breifast(
    cds: Annotated[stimela.Directory, Info("raw cube dataset")],
    timescales: Annotated[list[float | str], Info("timescales to process")] = None,
    candidate_threshold: Annotated[float, Info("candidate threshold")] = 6,
    dir_out: Annotated[stimela.Directory, Out, Info("output directory")] = None,
):
    """Multi-timescale breifast analysis."""

    detection_catalogs = []

    for timescale in timescales:
        # Classify — replaces =CASES(recipe.is-raw, ..., recipe.is-fd, ...)
        is_raw = timescale == 0
        is_fd = timescale == "FD"
        is_convolved = isinstance(timescale, (int, float)) and timescale > 0

        # Produce cube variant
        if is_convolved:
            step_cds = time_convolve(cds=cds, timescale_sec=timescale).out_cds
        elif is_fd:
            step_cds = forward_difference_cube(cds=cds).out_cds
        else:
            step_cds = cds

        # Threshold adjustment — replaces an inline Python-in-YAML cab
        adjust = 0
        if is_convolved:
            for ts_limit, adj in threshold_adjustments:
                if timescale >= ts_limit:
                    adjust = adj

        # Detect transients
        detections = render_detections(
            catalog=process_residual_cube(
                cds=step_cds, threshold=candidate_threshold + adjust,
            ).output_catalog,
            threshold=detection_threshold + adjust,
        )
        detection_catalogs.append(detections.output_catalog)

    return stimela.ResultNamespace(detection_catalogs=detection_catalogs)
```

The YAML `for_loop` with `output_elements` becomes a Python `for` loop with
`list.append()`. The `=CASES()` expression becomes `if/elif`. The inline
`adjust-threshold` cab (a Python snippet embedded in YAML with its own input/output
schema) becomes three lines of Python.

## 5. Migration from Stimela 2

### 5.1 What stays

- **Cab definitions**: YAML cab files in cultcargo and project packages are unchanged.
  They are auto-exposed as importable Python objects.
- **Backends**: Native, Apptainer (renamed from Singularity), Kubernetes, and SLURM
  backends are preserved with the same execution semantics.
- **Parameter validation**: Pydantic-based type checking is preserved.
- **CLI**: `stimela exec` runs Python recipes from the command line with automatic
  Click-based argument parsing.
- **Wranglers**: Regex-based output processors remain a cab-level concern, defined in
  the YAML or Python cab definition.

### 5.2 What changes

- **YAML recipes** are no longer the primary recipe format. They remain supported as a
  convenience for simple linear pipelines, with a future `stimela eject` command to
  transpile them to Python.
- **The expression evaluator** is not used by Python recipes. It remains available for
  YAML recipe compatibility and as the engine behind future transpilation.
- **`assign_based_on`**, **`for_loop`**, **`preamble`/`epilogue`**, and **`=formula`
  expressions** are replaced by native Python constructs.
- **Aliases** are replaced by explicit parameter passing to sub-recipe function calls.
- **`nom_de_guerre`** is replaced by `Annotated[type, stimela.Param(cli_name="...")]`
  for cabs that need a different CLI flag name than the Python parameter name.

### 5.3 Timeline

| Release | Content |
|---------|---------|
| v2.2 | Cleanup: dead code removal, Backend Protocol, confirmed bug fixes |
| v2.3 | Python recipe API added alongside YAML |
| v3.0 | Python API is primary. `stimela eject` transpiler for YAML → Python |

## 6. Relationship to hip-cargo

Stimela 3 and hip-cargo (Bester et al.) occupy complementary positions in the pipeline
lifecycle:

- **Stimela 3** is the development tool: flexible, full Python, multiple backends.
  Developers prototype and iterate pipelines here.
- **hip-cargo transpile** is the deployment tool: restricted grammar, Ray-orchestrated,
  auditable artifacts. Maintainers compile stable pipelines for shared HPC.

The Stimela 3 Python API is designed to be transpilable: a subset of Python recipes
(linear chains of cab calls with typed inputs/outputs) maps directly to hip-cargo's
Ray DAG model. The natural workflow is: write in Stimela 3, deploy via hip-cargo.

## 7. Conclusion

Stimela 3 replaces a YAML recipe language that grew to re-implement programming
constructs with Python itself. The core value of the framework — typed cab definitions,
backend dispatch, parameter validation — is preserved. What changes is the surface
language: instead of `assign_based_on`, recipes use `if`. Instead of `=IFSET()`,
`None` parameters are auto-skipped. Instead of `{steps.image.output}`, typed variables
carry results between steps. Instead of a 977-line expression evaluator, Python
provides expressions with proper error messages, IDE support, and debuggability.

The acid test — translating the 568-line TRON production pipeline — demonstrates that
the Python version is 29% shorter, statically analysable, and uses no framework-specific
control flow constructs. Every conditional, loop, and data reference is standard Python
that any developer can read without learning a domain-specific language.

## References

- Smirnov, O.M. et al. (2025). Stimela 2: An end-to-end radio interferometry
  framework. *Astronomy and Computing*.
  doi:10.1016/j.ascom.2025.100920

- Bester, L. (2026). hip-cargo transpile RFC: Compiling restricted YAML recipes to
  auditable Ray packages. https://github.com/landmanbester/hip-cargo
