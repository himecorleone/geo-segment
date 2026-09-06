# Verification · Geo Segment

Tested on 6 September 2026 with QGIS 3.44.10, bundled Python 3.12 and a
separate Python 3.12.10 environment on Apple Silicon.

## Version 0.3.0 checks

- 18 unit tests passed, including acceptance of 400 million pixels (10 km square)
  and exactly 500 million pixels, rejection just above the limit, disk-space
  checks, memory/disk path equivalence, and median-filter continuity across
  1024-pixel block seams and no-data strips.
- A full 25,000 × 20,000 synthetic raster (500 million valid pixels) completed
  preparation, 13,520 prediction tiles, block filtering and global polygonisation.
  All three synthetic regions were recovered and scratch files were removed.
  The check took 48.6 seconds with peak resident memory of 2.76 GB on this Mac.
  **Predictions were simulated:** these figures do not measure real model speed,
  real-model memory overhead or satellite detection accuracy at this scale.
- Real RAMP inference through QGIS and the external worker still returned 23
  valid regions on SpaceNet img10, with 19 matches against 28 references:
  precision 82.6%, recall 67.9%, F1 74.5%. This run took 3.74 seconds. GeoPackage
  export preserved classification metadata. Input removal cancelled inference,
  and the harness verified cleanup of interrupted-job scratch directories.
- Installed the 0.3.0 ZIP in the live QGIS Plugin Manager, confirmed the
  500-million-pixel capacity text and ran the satellite action successfully:
  23 building regions were added.
- Large non-byte imagery now uses bounded sampling for the percentile stretch;
  this can affect results relative to an exact whole-area stretch. Byte RGB and
  the small-area stretch keep their existing behaviour.
- A full-size run with real model predictions, general large-area accuracy,
  Windows cleanup and dense vector outputs have not been validated. The
  20,000-region output guard still applies. No resumable job support was added.

## Version 0.2.0 checks

- 15 unit tests passed. New cases cover tile-seam continuity without duplicate
  polygons, small edge tiles, rejection of invalid model output, no-data splits,
  metric minimum area, grid size limits, valid-pixel RGB stretching, alpha-aware
  raster warping, and embedding-cache reuse/invalidation/corruption recovery.
- QGIS SAM integration passed: capture, prompts, real prompted and automatic
  inference, isolated QProcess execution, cancellation, geometry validity,
  refinement, GeoPackage round trip, and clean unload. Repeated real SAM prompt
  jobs reused the embedding and produced identical polygon geometry.
- Empty results clear the latest export target while preserving earlier layers.
- The new building action ran on real SpaceNet Las Vegas satellite imagery
  through QGIS → QProcess → RAMP → valid UTM polygons → GeoPackage. No SAM
  capture was required. Model/class/review/area fields survived export.
- Removing the raster during a building job cancelled the process and prevented
  orphaned results from being added. The saved comparison project and preview
  rendered successfully.
- Installed the packaged 0.2.0 ZIP through the live QGIS Plugin Manager,
  configured the prepared RAMP model, passed the runtime check, clicked
  Detect buildings in current view and exported the 23-feature result.
  All live polygons are valid and their geometry set is identical to the
  offscreen integration result. Visually inspected the live reference overlay
  and the updated controls. The pre-existing LAStools-path error is unrelated.
- Python compilation, source whitespace checks and ZIP integrity passed. The
  previous installed plugin was backed up before the upgrade.

### Satellite diagnostic

SpaceNet 2 AOI_2_Vegas img10 has 28 reference building features. With the
default 10 m² minimum region size and IoU ≥0.5 one-to-one matching:

| Workflow | Regions | Matched | Unmatched | Missed | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Earlier SAM, ≥10 m² | 58 | 12 | 46 | 16 | 20.7% | 42.9% | 27.9% |
| Geo Segment 0.2 building mode | 23 | 19 | 4 | 9 | 82.6% | 67.9% | 74.5% |

The tested building action took approximately 3.8 seconds end to end on this
small tile. This is not a general speed guarantee. Both new building mode and
the earlier Deepness comparison use the same RAMP weights; their small score
difference reflects raster preparation/grid alignment, not a newly trained
model. Earlier SAM used a rendered capture. This is a one-scene workflow
diagnostic, not an independent model benchmark or a verified count. Touching
buildings can merge. External training overlap with the scene was not audited.

### Reference review and dependencies

Reviewed TerraLabAI/QGIS_AI-Segmentation commit
`1e2f9160ae7955ddfc6f07865f8a5f301cb07628`: separation of automatic/manual
workflows, crop-embedding reuse, tile completeness and geospatial output
handling informed the implementation. No TerraLab code or cloud API was added.
The building backend uses the previously tested Deepness RAMP ONNX model;
its exact SHA-256 is checked and documented in README.md. Added dependencies:
ONNX Runtime 1.29.0 and Shapely 2.1.2 in the external AI environment.

The first building harness run passed inference and export but failed when
passing an unreferenced rectangle to QGIS project view settings. The harness
was corrected to supply a QgsReferencedRectangle; the full rerun passed.
Offscreen Qt size-hint notices and the existing optional GDAL TMS-file warning
did not affect these checks.

Windows, Linux, other QGIS versions, GPU inference, large surveys, rotated or
multispectral production rasters and general object-count accuracy remain
unverified. Building mode currently supports local RGB rasters in UTM-covered
latitudes; SAM retains its existing rendered-raster path.

## Historical version 0.1.0 checks

Tested on 6 September 2026 on macOS / Apple Silicon using installed QGIS
**3.44.10-Solothurn**, its bundled Python 3.12, and a separate Python **3.12.10**
AI environment. No existing QGIS plugin was replaced or enabled during testing.

## Passed

- Eight unit tests: north-up map/pixel conversion, raster extent edges,
  negative/geographic coordinates, box conversion, invalid prompts, polygon
  holes and disconnected components, diagonal pixel topology, and no-data
  masking before minimum-area filtering.
- Real offscreen QGIS integration: plugin initialisation, dock creation,
  georeferenced GeoTIFF rendering, include/exclude points, undo, box prompts,
  CRS preservation, polygon hole area, refined-copy preservation, and
  GeoPackage write/read with geometry and CRS checks.
- Isolated AI interpreter launched from QGIS through `QProcess`.
- Cancellation of a running subprocess returned control and preserved the
  existing result layer.
- Real SAM ViT-B inference on a synthetic georeferenced raster, from QGIS
  capture through the external worker back into QGIS polygons. The prompted
  polygon contained the intended map point.
- Real automatic SAM mask generation on the same raster produced three
  objects and exported successfully to GeoPackage.
- Source-layer removal invalidated captures and prompts. Plugin unload and
  application shutdown completed with exit code 0.
- Python compilation; whitespace checks; ZIP integrity and required entry
  point/metadata checks.
- Visual inspection of the rendered dock at 1100 × 900 pixels. Long content
  remains accessible by scrolling.

The first integration harness run retained GDAL layer objects past QGIS
shutdown and exited with a teardown error. Releasing those references before
shutdown fixed the harness; subsequent integration runs exited cleanly.
Offscreen Qt emitted platform size-hint notices, and bundled GDAL reported a
missing optional `tms_NZTM2000.json` data file. These did not fail the tested
local GeoTIFF render or GeoPackage round trip.

## AI versions used

- torch 2.14.0; torchvision 0.29.0
- NumPy 2.5.2; Pillow 12.3.0; Rasterio 1.5.1
- SAM upstream commit `dca509fe793f601edb92606367a655c15ac00fdf`
- Official `sam_vit_b_01ec64.pth` checkpoint SHA-256:
  `ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912`

## Not yet verified

Real-world orthophoto accuracy, large/dense captures, Windows, Linux, older
QGIS 3 releases, CUDA, MPS inference and WMS/XYZ providers. QGIS 4 is excluded
from the plugin metadata. Tests exercise the actual QGIS runtime offscreen;
installation through the interactive Plugin Manager has not been performed.
The eight tests plus synthetic inference demonstrate functionality, not
accuracy against a labelled aerial-imagery benchmark.
