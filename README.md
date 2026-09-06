# Geo Segment for QGIS

Local building detection and interactive image segmentation for QGIS 3.
Use the RAMP building model to create georeferenced building regions, or use
Segment Anything (SAM) points and boxes to outline objects. Review and refine
polygons in QGIS, then export them to GeoPackage.

- Local inference in a separate Python environment, with no imagery uploads.
- Building inference in overlapping metric tiles with no-data handling.
- Cached SAM image embeddings for repeated prompts on the same capture.
- Class, model, area and review metadata on exported results.

**Experimental:** tested on macOS Apple Silicon with QGIS 3.44.10. Building
regions may merge neighbouring roofs or miss buildings; their count is not a
verified building count. SAM automatic masks are unlabelled. QGIS 4 is not
supported.

## Install

Clone or download this repository, then build the QGIS plugin ZIP:

```sh
python3 tools/package.py
```

In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**, select
`dist/geo_segment-0.2.0.zip`, and enable **Geo Segment**. Follow the
[setup and usage guide](geo_segment/README.md) to prepare a separate Python
3.10–3.12 environment and download the required model weights.

Model weights, imagery and local test outputs are not included in this
repository or the plugin ZIP. The plugin does not download them automatically.

## Development

Run the dependency-free coordinate tests:

```sh
python3 -m unittest discover -s tests -p 'test_spatial.py'
```

With both AI requirements files installed in your external environment:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

`tests/qgis_smoke.py` requires QGIS Python; `tools/test_qgis_macos.sh` targets the
tested macOS QGIS bundle. `tests/qgis_buildings.py` is an optional local satellite
integration harness: it expects the prepared SpaceNet fixtures under
`dist/satellite-test`, the AI environment at `.venv`, and the RAMP checkpoint
under `models`. These external fixtures are not part of the repository.

See the [validation record](geo_segment/VALIDATION.md) for completed tests,
a one-scene satellite diagnostic and remaining platform/accuracy limitations.

## Licence

Original Geo Segment code is licensed under [MIT](LICENSE).
Dependencies and model weights retain their own licences; see
[third-party notices](geo_segment/THIRD_PARTY.md).
