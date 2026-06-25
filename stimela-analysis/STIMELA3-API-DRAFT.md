# Stimela3 Python API — Draft v0.1

**Date**: 2026-06-25
**Status**: First iteration, for discussion
**Goal**: Show what real Stimela recipes look like in Python, side-by-side with the YAML

---

## Design Principles

1. **Recipes are Python functions.** A `@stimela.recipe` decorator marks a function as a recipe. Parameters become recipe inputs.
2. **Steps are function calls.** `stimela.run("cab_name", param=value)` runs a cab and returns its outputs.
3. **Python IS the control flow.** No `assign_based_on`, no `=IF(VALID(...))`, no `for_loop` YAML keyword. Use `if`, `for`, f-strings.
4. **Sub-recipes are function calls.** Composability = calling one recipe from another.
5. **Existing cab definitions work unchanged.** YAML cabs from cultcargo load into the same registry. No migration needed for cabs.
6. **The caracal lesson**: No `recipe.add()`. No manual parameter dicts. No god functions. Structure comes from the decorator pattern and function composition, not discipline.

---

## Example 1: Simple Linear Recipe

### Stimela2 YAML (from test_recipe.yml)

```yaml
recipe:
  name: "demo recipe"
  aliases:
    msname: selfcal.ms
    telescope: makems.tel
  defaults:
    telescope: kat-7
    selfcal.image.size: 1024
  inputs:
    band:
      choices: [L, UHF, K]
      default: L
  assign_based_on:
    band:
      L:
        var1: x
        var2: y
        config.cabs.wsclean.inputs.dummy.default: 1000
        band_label: "band1-{recipe.band}"
        test_callable.b: LBAND
      UHF:
        var1: x1
        var2: y1
        config.cabs.wsclean.inputs.dummy.default: 2000
        band_label: "band2-{recipe.band}"
        test_callable.b: UHF
      DEFAULT:

  steps:
      test_callable:
        cab: test_callable
        params:
          a: 1
          b: foo

      makems:
          cab: simms
          params:
              msname: "{recipe.msname}"
              synthesis: 0.128
      selfcal:
          params:
            band_name: "{recipe.band_label}"
          recipe:
              name: "demo selfcal"
              steps:
                  calibrate:
                      cab: cubical
                      params:
                        jones: [B,G]
                  image:
                      cab: wsclean
                      params:
                          scale: "{recipe.scale}"
                          dummy2: "{recipe.band_name}"
                  evaluate:
                      cab: aimfast
                      params:
                          image: "{previous.restored}"
                          dirty: "{steps.image.dirty}"
              aliases:
                  ms: [calibrate.ms, image.ms]
                  image_name: image.prefix
              inputs:
                  scale:
                    dtype: Union[str, float]
                  band_name:
                    dtype: str
              defaults:
                  scale: 30asec
```

### Stimela3 Python

```python
import stimela
from stimela import Choices

@stimela.recipe
def selfcal(ms: str, scale: str = "30asec", band_name: str = ""):
    """One round of calibration + imaging + evaluation."""
    cal = stimela.run("cubical", ms=ms, jones=["B", "G"])

    img = stimela.run("wsclean", ms=ms, scale=scale, dummy2=band_name)

    stimela.run("aimfast", image=img.restored, dirty=img.dirty)

    return img


@stimela.recipe
def demo_recipe(
    msname: str,
    telescope: str = "kat-7",
    band: Choices["L", "UHF", "K"] = "L",
):
    """Demo pipeline: simulate MS, then selfcal."""
    # Python replaces assign_based_on
    if band == "L":
        band_label = f"band1-{band}"
        dummy_default = 1000
    elif band == "UHF":
        band_label = f"band2-{band}"
        dummy_default = 2000
    else:
        band_label = band
        dummy_default = None

    stimela.run("test_callable", a=1, b="foo")

    ms = stimela.run("simms", msname=msname, synthesis=0.128)

    # Sub-recipe is a function call
    selfcal(ms=ms.ms, band_name=band_label)
```

**What changed:**
- 54 lines of YAML → 30 lines of Python (44% shorter)
- `assign_based_on` → Python `if/elif` (debuggable, IDE-supported)
- `"{recipe.band_label}"` → `band_label` (Python variable)
- Nested recipe definition → separate function (composable, testable)
- `aliases` → function arguments (explicit parameter passing)
- `"{previous.restored}"` → `img.restored` (typed attribute access)

---

## Example 2: For-Loop with Scatter

### Stimela2 YAML (from test_scatter.yml)

```yaml
lib:
  recipes:
    multi_echo:
      info: 'runs multiple echo cabs'
      inputs:
        args:
          dtype: List[str]
          required: true
      for_loop:
        var: arg
        over: args
      steps:
        sleep:
          cab: sleep
        echo:
          cab: echo
          params:
            arg: =recipe.arg

basic_loop:
  _use: lib.recipes.multi_echo
  defaults:
    args: [1,2,3,4,5,6,7,8,9,10]
  inputs:
    for_loop:
      scatter:
        dtype: int
        default: -1

nested_loop:
  for_loop:
    var: subloop
    over: subloops
  inputs:
    subloops:
      dtype: List[str]
      default: [a,b,c]
    for_loop:
      scatter:
        dtype: int
        default: -1
  steps:
    subloop-1:
      recipe: basic_loop
    subloop-2:
      recipe: basic_loop
```

### Stimela3 Python

```python
import stimela

@stimela.recipe
def multi_echo(args: list[str]):
    """Run echo for each argument."""
    for arg in args:
        stimela.run("sleep")
        stimela.run("echo", arg=arg)


@stimela.recipe
def basic_loop(args: list[str] = None):
    """Same as multi_echo but scattered (parallel)."""
    if args is None:
        args = [str(i) for i in range(1, 11)]

    with stimela.parallel() as pool:
        for arg in args:
            pool.run("sleep")
            pool.run("echo", arg=arg)


@stimela.recipe
def nested_loop(subloops: list[str] = None):
    """Nested parallel loops."""
    if subloops is None:
        subloops = ["a", "b", "c"]

    with stimela.parallel() as pool:
        for subloop in subloops:
            pool.call(basic_loop, args=[str(i) for i in range(1, 11)])
```

**What changed:**
- `for_loop` YAML keyword → Python `for` loop
- `scatter` → `stimela.parallel()` context manager
- `_use: lib.recipes.multi_echo` → function call
- `=recipe.arg` → `arg` (Python variable)
- Nested loops are just nested function calls

---

## Example 3: Selfcal Loop with Conditional Skipping

### Stimela2 YAML (from test_loop_recipe.yml)

```yaml
cubical_image_loop:
  assign:
    dir:
      out: 'output'
    image-prefix: "{recipe.dir.out}/im{info.suffix}-{recipe.loop-name}/..."
    loop-name: "s{recipe.loop:02d}"

  assign_based_on:
    loop:
      '1':
        z: 1
      '2':
        z: 2
      DEFAULT:
        z: 3

  for_loop:
    var: loop
    over: [1,2,3]

  aliases:
    ms: [calibrate.ms, image-1.ms]

  steps:
    calibrate:
        cab: cubical
        skip: "=recipe.loop == 1"
    image-1:
        cab: myclean
        params:
          prefix: "{recipe.image-prefix}"
```

### Stimela3 Python

```python
import stimela

@stimela.recipe
def cubical_image_loop(ms: str, output_dir: str = "output"):
    """Calibrate and image over 3 iterations, skipping cal on first."""
    for loop in [1, 2, 3]:
        loop_name = f"s{loop:02d}"
        image_prefix = f"{output_dir}/im-{loop_name}/im-{loop_name}"

        # Skip calibration on first iteration
        if loop > 1:
            stimela.run("cubical", ms=ms)

        stimela.run("myclean", ms=ms, prefix=image_prefix)
```

**What changed:**
- 30 lines of YAML → 12 lines of Python (60% shorter)
- `assign` + `assign_based_on` → Python variables + f-strings
- `skip: "=recipe.loop == 1"` → `if loop > 1:` (obviously correct)
- `"{recipe.image-prefix}"` → `image_prefix` (no custom substitution engine)
- `aliases: ms: [calibrate.ms, image-1.ms]` → pass `ms` directly to both steps

---

## The API Surface

### Core functions

```python
stimela.run(cab_name, **params) -> RunResult
```

Runs a cab. Loads the cab definition from the registry (YAML or Python), validates parameters via pydantic, constructs the command line, dispatches to the configured backend. Returns a `RunResult` with output attributes.

```python
stimela.parallel() -> ParallelContext
```

Context manager for parallel execution. Steps launched via `pool.run()` or `pool.call()` execute concurrently. Results are available after the context exits.

### Decorators

```python
@stimela.recipe
def my_recipe(param: type = default): ...
```

Marks a function as a Stimela recipe. The function's signature defines the recipe's inputs. Type annotations provide the schema. Generates a CLI via Click when run from the command line.

```python
@stimela.cab(command="tool_name")
def my_cab(input1: str, input2: int = 0) -> stimela.Outputs(out=File): ...
```

Optional: define a cab in Python instead of YAML. The decorator generates the same internal representation as the YAML cab loader.

### Result objects

```python
result = stimela.run("wsclean", ms="obs.ms", size=4096)
result.restored     # output file path (typed)
result.dirty        # another output
result.success      # bool
result.log          # log output
```

Outputs are accessible as typed attributes. The attribute names come from the cab's output schema.

### Backend selection

```python
# In config (stimela.conf or environment)
backend: singularity

# Per-recipe
@stimela.recipe(backend="native")
def my_recipe(): ...

# Per-step
stimela.run("wsclean", ms=ms, _backend="kube")
```

### Running from CLI

```bash
# Run a Python recipe
stimela exec pipeline.py demo_recipe msname=obs.ms band=L

# Run with a parameter file
stimela exec pipeline.py demo_recipe --parameter-file params.yml

# Run with specific backend
stimela exec pipeline.py demo_recipe msname=obs.ms -b singularity
```

---

## What About `{previous.restored}`?

In YAML recipes, `{previous.restored}` refers to the previous step's output. In Python, this is just a variable:

```python
# YAML way:
#   image: "{previous.restored}"

# Python way — the variable IS the reference:
img = stimela.run("wsclean", ...)
stimela.run("aimfast", image=img.restored)
```

No substitution engine needed. Python's scoping rules handle it.

---

## What About Wranglers?

Wranglers (regex-based output processors) are a cab-level concern, not a recipe concern. They stay in the YAML cab definition:

```yaml
# In cultcargo cab definition (unchanged)
cabs:
  wsclean:
    wranglers:
      "error reading file (.*)": DeclareError
      "WARNING: (.*)": ChangeSeverity WARNING
```

Or in Python cab definitions:

```python
@stimela.cab(
    command="wsclean",
    wranglers={
        r"error reading file (.*)": stimela.DeclareError,
        r"WARNING: (.*)": stimela.ChangeSeverity("WARNING"),
    },
)
def wsclean(ms: MS, size: int = 4096) -> stimela.Outputs(restored=File):
    ...
```

---

## What About `nom_de_guerre`?

Gone. In Python cabs, the parameter name IS the CLI flag name. If a tool uses a different flag:

```python
@stimela.cab(command="cubical")
def cubical(
    ms: MS = stimela.Param(cli_name="data-ms"),
):
    ...
```

Or just name the parameter what the tool expects and use a descriptive docstring.

---

## Comparison Summary

| Aspect | YAML (Stimela2) | Python (Stimela3) |
|--------|-----------------|-------------------|
| Recipe definition | YAML block with `name`, `inputs`, `steps` | Function with `@stimela.recipe` decorator |
| Parameter schema | `dtype`, `required`, `choices` fields | Type annotations + defaults |
| Step invocation | `cab: wsclean` under `steps:` | `stimela.run("wsclean", ...)` |
| Variable substitution | `"{recipe.param}"` | Python variable |
| Conditional logic | `assign_based_on` + `skip:` expressions | `if`/`elif`/`else` |
| Loops | `for_loop:` YAML block | `for x in items:` |
| Parallel execution | `scatter:` under `for_loop` | `stimela.parallel()` context manager |
| Sub-recipes | Nested `recipe:` block or `_use:` | Function call |
| Output references | `"{previous.restored}"`, `"{steps.image.dirty}"` | `result.restored`, `img.dirty` |
| Expression evaluation | `=BASENAME(recipe.ms)` | `Path(ms).stem` |

---

## Open Design Questions

### 1. How does `stimela.run()` find the cab?

Option A — global registry (like current cultcargo):
```python
stimela.run("wsclean", ms=ms)  # looks up "wsclean" in global cab registry
```

Option B — explicit import:
```python
from cultcargo import wsclean
wsclean.run(ms=ms)  # or wsclean(ms=ms)
```

Option A is simpler and matches current usage. Option B gives IDE autocomplete on cab names.

### 2. How are outputs declared for Python cabs?

```python
# Option A: return annotation
@stimela.cab(command="wsclean")
def wsclean(ms: MS) -> stimela.Outputs(restored=File, dirty=File): ...

# Option B: decorator parameter
@stimela.cab(command="wsclean", outputs={"restored": File, "dirty": File})
def wsclean(ms: MS): ...

# Option C: class-based
class WscleanOutputs(stimela.Outputs):
    restored: File
    dirty: File
```

### 3. Should `stimela.run()` raise on failure or return a result?

```python
# Option A: raise (like subprocess.run(check=True))
result = stimela.run("wsclean", ms=ms)  # raises on failure

# Option B: return result, check explicitly
result = stimela.run("wsclean", ms=ms, check=False)
if not result.success:
    handle_error()
```

Recommendation: raise by default (most recipes want fail-fast), with `check=False` opt-out.

---

## Example 4: The Acid Test — TRON Pipeline (tron-pfb.yml)

The full translation of `breifast/recipes/tron-pfb.yml` — a 568-line real-world transient
detection pipeline — is in [`tron-pfb-python.py`](tron-pfb-python.py).

**Result: 568 lines YAML to 290 lines Python** (steps only, excluding config dataclasses).

Key patterns the acid test revealed:

| YAML pattern | Python equivalent | Occurrences |
|---|---|---|
| `=IFSET(recipe.param)` | `param` (None auto-skipped by `stimela.run`) | ~20x |
| `=STRIPEXT(x) + '.fits'` | `Path(x).with_suffix(".fits")` | ~10x |
| `skip: =not recipe.flag` | `if flag:` | 4x |
| `skip_if_outputs: fresh` | `_cache="fresh"` | ~15x |
| `=steps.X.output` | `x_result.output` (typed variable) | ~30x |
| `tags: [a, b]` | `_tags=["a", "b"]` | ~15x |
| `backend: select: singularity` | `_backend="singularity"` | 1x |

The `=IFSET()` pattern is particularly telling: it appears ~20 times in the YAML because
every optional parameter needs explicit "pass only if set" handling. In Python, `None`
parameters are auto-skipped — the entire pattern vanishes.

See the full side-by-side in the companion file.
