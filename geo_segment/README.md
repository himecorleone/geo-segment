# Geo Segment · QGIS plugin

Version 0.3.0 is an independent local segmentation plugin for QGIS 3.28–3.44.
It combines a class-specific RAMP building model with Meta's Segment Anything
(SAM) for interactive object boundaries. It contains no TerraLab code, branding,
account integration or cloud service. TerraLab's repository was reviewed as a
workflow reference; our automatic building inference runs locally.

## Install the plugin

In QGIS, choose **Plugins → Manage and Install Plugins → Install from ZIP**,
select `geo_segment-0.3.0.zip`, and enable **Geo Segment**. Open it from the
Raster menu or the teal polygon toolbar button.

## Set up local AI once

Use Python 3.10–3.12 in a separate virtual environment. Do not install AI
packages into QGIS's bundled Python. Internet is needed for this initial setup.
Run the following from the extracted `geo_segment` folder:

macOS / Linux:

```sh
python3.12 -m venv "$HOME/.geo-segment-ai"
"$HOME/.geo-segment-ai/bin/python" -m pip install -r requirements-ai.txt
```

Windows PowerShell:

```powershell
py -3.12 -m venv "$env:USERPROFILE\.geo-segment-ai"
& "$env:USERPROFILE\.geo-segment-ai\Scripts\python.exe" -m pip install -r requirements-ai.txt
```

Git is required for the pinned upstream SAM package. CUDA users should follow
the [official PyTorch installation selector](https://pytorch.org/get-started/locally/)
for a matching GPU build before installing these requirements.

Download the [official SAM ViT-B checkpoint (about 375 MB)](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth)
to a permanent local folder. In the plugin's **Settings** tab:

1. Select the virtual environment's `bin/python` or `Scripts/python.exe`.
2. Select the `.pth` checkpoint and choose its matching model type (`vit_b`).
3. Click **Save settings and check AI runtime**.

Auto chooses CUDA if available, otherwise CPU. MPS on Apple Silicon can be
selected explicitly; use CPU if an unsupported MPS operation occurs. Checkpoints
are loaded with PyTorch's `weights_only=True` option. No model files are bundled.

## Detect buildings from a local raster

Install `requirements-buildings.txt` into the **same AI environment**, using
that environment's Python and `-m pip install -r requirements-buildings.txt`.
Download the [RAMP XUnet building model from the Deepness model zoo](https://chmura.put.poznan.pl/s/MwhgQNhyQF3fuBs)
and select it in **Settings → RAMP building model (.onnx)**. This version checks
the tested file's SHA-256 before loading it:

`29709ab0ed665f239e60ff2f5dbdcc70bdcb3d2d045a8934387a9bab279d5554`

1. Select a local georeferenced raster whose first three bands are **red, green,
   blue**. Alpha/no-data metadata is honoured. Reorder multispectral bands first
   if necessary; their meaning is not inferred from band names.
2. Zoom to the area, set **Minimum building area** (default 10 m²), and choose
   **Detect buildings in current view**. No SAM capture or checkpoint is needed
   for this action.
3. Review **building regions**, especially merged neighbouring roofs, missed
   buildings and non-building detections. Export to keep the result.

The worker reads only the selected area, reprojects to local UTM at 0.5 m/pixel,
processes 256-pixel tiles with 25% overlap, joins tile cores before polygonising
and applies the tested model's 11-pixel median filter. These fixed defaults
come from the downloaded model metadata; the online model-zoo table instead
lists 0.4 m. Byte RGB is preserved; other numeric RGB receives a 2–98 percentile
stretch over valid pixels in the selected area. QGIS display styling is not
applied in this mode. Jobs accept up to **500 million inference pixels**
(125 km² at 0.5 m/pixel). A 10 km × 10 km area uses 400 million pixels and fits.
The limit is checked after intersection with the raster and snapping to the
metric grid; the previous 8192-pixel side restriction has been removed.

Areas above 16 million pixels use disk-backed RGB, validity and prediction
arrays. Raster preparation and median filtering run in bounded blocks, with
filter halos that preserve continuity across block boundaries. Polygonisation
uses one stitched raster, so processing blocks do not create separate copies
of buildings. At the full limit, allow at least **4 GB of free temporary disk
space**, in addition to your source raster and exported results. The worker
checks available space before creating its large arrays.

For large non-byte rasters, the 2–98 percentile stretch uses one evenly spaced
sample of up to one million pixels over the area. If that sample misses all
valid data, the first valid block supplies the stretch. Byte RGB is preserved,
and small-area stretching retains the earlier exact calculation. This sampling
can change results on higher-bit imagery compared with a whole-area percentile.

Inference remains sequential on the CPU. Large real-model jobs may take hours;
the capacity check with simulated predictions is not an inference-speed
benchmark. Cancel stops the job and QGIS removes its scratch files; completed
jobs also clean up. A crash can leave temporary files. There is no resume from
a cancelled or interrupted job. The separate **20,000 building-region limit**
remains in place to bound vector output; a dense area may need smaller sections
even when it fits the pixel limit.

Each connected region becomes one feature. **A region count is not a verified
building count**: adjacent buildings may merge. Fields record `class_name`,
`model`, `area_m2`, `score_type` and `review=unreviewed`. RAMP has no object-level
confidence in this workflow, so its `score` is NULL. This mode does not accept
text prompts or detect other classes. Only the tested model above is accepted.
Weights and training data have separate licences; consult their upstream
sources before redistribution.

## Segment imagery with SAM

1. Load a raster into QGIS (for example an orthophoto GeoTIFF), set the project
   CRS, and zoom to a small area. Choose the raster in Geo Segment.
2. Choose a capture resolution and click **Capture current view**. Only the
   selected raster is rendered, using its current QGIS styling. A teal outline
   marks the capture. Transparent/no-data pixels are excluded from masks.
3. For an individual object, use **Add points**: left click includes an area,
   right click excludes it. Optionally draw a bounding box. Click **Segment
   prompted object**. Add more points and rerun to improve the outline. Clear
   prompts before starting a different object.
4. Alternatively, use **Find unlabelled masks in capture** to generate automatic
   masks over the entire capture. This ignores existing point/box prompts.
5. Inspect the new temporary polygon layer. Adjust simplify, expand/shrink or
   fill holes, then create a refined copy. These distances are **result pixels**,
   converted into the output CRS's map units; they are not metres.
   One building-result pixel represents 0.5 metres; SAM uses the capture scale.
6. Export the latest result to a **new** GeoPackage file. Other result layers
   can be exported with QGIS's normal layer export commands. Temporary layers
   must be exported to persist their geometry across QGIS sessions.

Zoom or pan does not move an existing capture. Recapture after changing imagery,
styles or the intended area. Switching source layers or project CRS invalidates
the capture. The rendered image is north-up even if the canvas is rotated.

Each run creates a separate result layer. Native QGIS editing tools can modify,
delete, split or merge those polygons. Refinement operates on the latest result
including edits, creates a new copy, and preserves the previous layer. Repeated
refinement is cumulative. `pixels` and `score` always describe the original AI
mask; SAM's `score` is a model quality estimate, not a class probability.
`area_m2` is updated after refinement. Empty jobs preserve earlier layers but
clear the latest-result export target, preventing an old output being mistaken
for the result of a new job.

## Scope and limitations

- SAM automatic masks are **unlabelled**, can overlap or describe parts of objects,
  and need review. Use the separate building action for class-specific regions.
- Each SAM capture is one rendered image, capped at 2048 pixels on its longest side.
  It does not tile large survey areas at native raster resolution. Zoom in for
  small objects, and repeat captures for other areas.
- The model is loaded for every run. Repeated SAM prompt jobs reuse one cached
  image embedding, avoiding repeated image encoding. Changed pixels, dimensions
  or checkpoint identity invalidate it. There is no hover preview. CPU automatic
  inference can take several minutes.
- Local rasters are the primary tested input. QGIS-renderable WMS/XYZ raster
  layers use the same render path, but network imagery depends on its provider
  and has not been independently verified. Normal tile downloads may occur.
- Inference uses local files with no imagery uploads, telemetry or accounts.
  Captures and job files are removed when the plugin unloads normally. A crash
  may leave files in the operating system's temporary directory.
- Runtime check verifies imports and compute availability; an actual run also
  checks checkpoint compatibility. No automatic model/package downloads occur
  inside QGIS.
- QGIS 4 / Qt 6 compatibility is not claimed by this first release.

## Development and verification

`plugin.py` contains the Qt interface, asynchronous QGIS renderer, map tools,
process lifecycle, polygon review and GeoPackage export. `worker.py` runs in
the AI environment and converts SAM masks with Rasterio, preserving holes and
disconnected components. `buildings.py` implements bounded, tiled RAMP inference.
`spatial.py` defines the map/pixel coordinate contract.

From the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_spatial.py'
# With AI dependencies:
python -m unittest discover -s tests -p 'test_worker.py'
python -m unittest discover -s tests -p 'test_buildings.py'
# With QGIS Python available:
QT_QPA_PLATFORM=offscreen python tests/qgis_smoke.py
python tools/package.py
```

See `VALIDATION.md` in this folder for actual verification and any remaining
gaps. Source references: [SAM](https://github.com/facebookresearch/segment-anything),
[QGIS map settings](https://api.qgis.org/api/3.40/classQgsMapSettings.html), and
[QGIS vector writer](https://api.qgis.org/api/classQgsVectorFileWriter.html).

Geo Segment original source is offered under the MIT licence; see `LICENSE`.
Runtime dependencies and model weights retain their own licences; see
`THIRD_PARTY.md`.

References: [TerraLabAI's workflow](https://github.com/TerraLabAI/QGIS_AI-Segmentation),
[Deepness model zoo](https://qgis-plugin-deepness.readthedocs.io/en/latest/main/main_model_zoo.html)
and [Deepness source](https://github.com/PUTvision/qgis-plugin-deepness).
