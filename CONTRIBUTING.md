# Contributing to Geo Segment

Bug reports, documentation fixes and focused pull requests are welcome.
Use [Issues](https://github.com/himecorleone/geo-segment/issues) for reproducible
bugs or feature proposals. For a substantial change, describe the intended
workflow in an issue before implementing it so maintainers can discuss scope.

## Development setup

Fork the repository and clone your fork. Work on a branch and use a separate
Python environment; do not install AI dependencies into QGIS's bundled Python.

```sh
python3.12 -m venv .venv
# macOS / Linux; on Windows use .venv\Scripts\python.exe
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python tools/package.py
```

These unit tests need no QGIS installation, model downloads or satellite data.
The development requirements include PyTorch for the embedding-cache tests.
Actual inference additionally needs the runtime requirements and separate
checkpoints described in the [user guide](geo_segment/README.md).

## Repository layout

| Location | Purpose |
|---|---|
| `geo_segment/plugin.py` | QGIS interface, capture, job lifecycle, review and export |
| `geo_segment/worker.py` | External SAM worker and embedding cache |
| `geo_segment/buildings.py` | Tiled RAMP building inference |
| `geo_segment/spatial.py` | Map/pixel coordinate contract |
| `geo_segment/README.md` | Installation and user guide, included in the plugin ZIP |
| `geo_segment/VALIDATION.md` | Completed validation and known limits |
| `tests/` | Unit tests and optional QGIS integration harnesses |
| `tools/` | Plugin packaging and local QGIS test launcher |
| `.github/` | Automated checks, issue and pull-request templates |

`models/`, `dist/` and local virtual environments are ignored. Do not commit
credentials, personal machine paths, checkpoints, imagery or generated outputs.

## Checks before a pull request

- Keep the change focused and follow the existing structure and Python style.
- Run the relevant unit tests. Add a regression test when fixing a substantive bug.
- For QGIS interface or process changes, run `tests/qgis_smoke.py` with QGIS
  Python. On the tested macOS bundle, use `sh tools/test_qgis_macos.sh`.
  Set `GEO_SEGMENT_AI_PYTHON` to your AI interpreter and optionally
  `GEO_SEGMENT_CHECKPOINT` to exercise real SAM inference.
- Building integration in `tests/qgis_buildings.py` requires the prepared local
  SpaceNet img10 fixture, `.venv` and RAMP model paths listed in the root README.
  State when this optional check was not run.
- Run `python tools/package.py`; install the resulting ZIP in QGIS when the
  change affects installation or UI behaviour. Update the guide and changelog
  for user-visible changes.

GitHub Actions runs unit tests and builds the ZIP on Python 3.10 and 3.12.
It does not validate QGIS interaction, model inference or detection accuracy.
Describe the problem, resulting behaviour and actual checks in your pull request.
Do not include private imagery in a report; a small redistributable example is
preferable. Keep discussion respectful and practical.

## Optional large-area capacity check

With the AI/building runtime dependencies and supported RAMP file available:

```sh
.venv/bin/python tools/check_large_area.py
```

This processes a synthetic 500-million-pixel raster with simulated model
scores and verifies connected output and scratch cleanup. Allow 4 GB of free
temporary storage. It measures the raster data path, not neural-inference speed
or detection accuracy. `GEO_SEGMENT_TEST_OUTPUT` can redirect the optional QGIS
building harness output without replacing earlier validation artefacts.

## Licence

By submitting a contribution, you agree to make your original contribution
available under this project's MIT licence. Retain required third-party notices
and discuss new dependencies or model-distribution requirements in the pull request.
