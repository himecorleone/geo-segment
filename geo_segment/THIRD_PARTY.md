# Third-party dependencies and references

The MIT licence covers the original Geo Segment source. It does not relicense
QGIS, Python packages, model weights or imagery used with the plugin. None of
these third-party runtimes, model weights or datasets are bundled in this
repository or the plugin ZIP. Consult each upstream project's licence and the
terms attached to the specific version or model you use.

## Runtime dependencies

- [QGIS](https://github.com/qgis/QGIS): host application, GPL-2.0-or-later.
  Qt/PyQt and other libraries supplied by QGIS retain their upstream terms.
- [Segment Anything](https://github.com/facebookresearch/segment-anything):
  SAM runtime, Apache-2.0; installed from the pinned upstream commit in
  `requirements-ai.txt`. Download its checkpoint separately from Meta.
- [PyTorch](https://github.com/pytorch/pytorch) and
  [torchvision](https://github.com/pytorch/vision): upstream BSD-style licences.
- [NumPy](https://github.com/numpy/numpy),
  [Pillow](https://github.com/python-pillow/Pillow),
  [Rasterio](https://github.com/rasterio/rasterio),
  [ONNX Runtime](https://github.com/microsoft/onnxruntime) and
  [Shapely](https://github.com/shapely/shapely): separately installed packages;
  their licence files and bundled dependency notices apply.

## Building model and workflow references

The building backend is an independent implementation using a separately
provided RAMP XUnet ONNX model listed by the
[Deepness model zoo](https://qgis-plugin-deepness.readthedocs.io/en/latest/main/main_model_zoo.html).
The exact supported file and checksum are documented in `README.md`. The
Deepness plugin's software licence does not by itself establish permission to
redistribute a model or its training data; consult the model's upstream terms.

[TerraLabAI/QGIS_AI-Segmentation](https://github.com/TerraLabAI/QGIS_AI-Segmentation)
was reviewed for workflow ideas. No TerraLab source code, branding or cloud
API integration is included. Geo Segment is an independent project.

## Validation data

The published diagnostic used
[SpaceNet 2 building imagery and annotations](https://spacenet.ai/spacenet-buildings-dataset-v2/),
AOI_2_Vegas, tile img10. Those files are distributed separately by SpaceNet
Partners under CC-BY-SA-4.0 and are not included here. Reported results are a
single-scene workflow diagnostic, not a general accuracy benchmark.
