# Geo Segment for QGIS

[![Tests and package](https://github.com/himecorleone/geo-segment/actions/workflows/ci.yml/badge.svg)](https://github.com/himecorleone/geo-segment/actions/workflows/ci.yml)
[![MIT licence](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

[User guide](geo_segment/README.md) · [Contributing](CONTRIBUTING.md) ·
[Changelog](CHANGELOG.md) · [Report a bug](https://github.com/himecorleone/geo-segment/issues/new/choose)

Local building detection and interactive image segmentation for QGIS 3.
Use the RAMP building model to create georeferenced building regions, or use
Segment Anything (SAM) points and boxes to outline objects. Review and refine
polygons in QGIS, then export them to GeoPackage.

- Local inference in a separate Python environment, with no imagery uploads.
- Building inference in overlapping metric tiles with no-data handling, up to
  500 million pixels (125 km² at 0.5 m/pixel), using disk storage for large jobs.
- Cached SAM image embeddings for repeated prompts on the same capture.
- Class, model, area and review metadata on exported results.

**Experimental:** tested on macOS Apple Silicon with QGIS 3.44.10. Building
regions may merge neighbouring roofs or miss buildings; their count is not a
verified building count. SAM automatic masks are unlabelled. QGIS 4 is not
supported.

## Install

Download the installable plugin ZIP from [Releases](https://github.com/himecorleone/geo-segment/releases),
or clone this repository and build it yourself:

```sh
python3 tools/package.py
```

In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**, select
`dist/geo_segment-0.3.0.zip`, and enable **Geo Segment**. Follow the
[setup and usage guide](geo_segment/README.md) to prepare a separate Python
3.10–3.12 environment and download the required model weights.

Model weights, imagery and local test outputs are not included in this
repository or the plugin ZIP. The plugin does not download them automatically.

## Development

Run the dependency-free coordinate tests:

```sh
python3 -m unittest discover -s tests -p 'test_spatial.py'
```

Install `requirements-dev.txt` in a separate environment to run the full unit
suite without downloading model weights:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_*.py'
```

`tests/qgis_smoke.py` requires QGIS Python; `tools/test_qgis_macos.sh` targets the
tested macOS QGIS bundle. `tests/qgis_buildings.py` is an optional local satellite
integration harness: it expects the prepared SpaceNet fixtures under
`dist/satellite-test`, the AI environment at `.venv`, and the RAMP checkpoint
under `models`. These external fixtures are not part of the repository.

See the [validation record](geo_segment/VALIDATION.md) for completed tests,
a one-scene satellite diagnostic and remaining platform/accuracy limitations.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repository layout, development
setup and pull-request guidance. GitHub Actions checks unit tests and ZIP
packaging; real QGIS and inference checks remain separate.

## Licence

Original Geo Segment code is licensed under [MIT](LICENSE).
Dependencies and model weights retain their own licences; see
[third-party notices](geo_segment/THIRD_PARTY.md).
