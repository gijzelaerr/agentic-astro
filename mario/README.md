# Mario: Museek + Simeer Integration

Inject Simeer-simulated sky signal into the Museek pipeline so downstream
plugins process fake data without knowing.

## Setup

```bash
cd mario

# Clone the repos
git clone https://github.com/meerklass/museek.git
git clone https://github.com/meerklass/ivory.git
git clone https://github.com/zzhang0123/Simeer.git

# Create a Python 3.12 venv (Museek requires <3.13)
python3.12 -m venv .venv
source .venv/bin/activate

# Install all three packages
pip install -e ./ivory -e ./museek -e ./Simeer

# Copy the SimeerPlugin into Museek's plugin directory
cp simeer_plugin.py museek/museek/plugin/simeer_plugin.py
```

## Quick demo (no real data needed)

```bash
source .venv/bin/activate
python3 demo_simeer.py
```

Runs Simeer with synthetic pointing and beam, produces a waterfall plot.

## Full pipeline with real data

Edit `config_simeer.py` to set your `block_name` and `data_folder`, then:

```bash
source .venv/bin/activate
ivory config_simeer
```

Pipeline: `InPlugin → SimeerPlugin → NoiseDiodeFlagger → KnownRfi → ScanTrackSplit → ...`

## How it works

1. **InPlugin** reads real MeerKAT data via katdal, creating a `TimeOrderedData`
   with dish pointing coordinates (az, el), timestamps, and frequencies.

2. **SimeerPlugin** extracts those coordinates, computes LST from timestamps,
   and calls `simeer.integrate_tod()` per antenna to generate beam-weighted
   sky signal. The simulated `(n_freq, n_time)` array replaces the real
   visibility data.

3. **Downstream plugins** (flagging, calibration, mapmaking) run on the
   simulated data without any changes.

## Files

- `simeer_plugin.py` — Museek plugin that runs Simeer and injects simulated data
- `config_simeer.py` — Ivory pipeline config with SimeerPlugin inserted after InPlugin
- `demo_simeer.py` — Standalone demo script for the workshop
- `create_test_dataset.py` — Generate artificial test data for local testing
