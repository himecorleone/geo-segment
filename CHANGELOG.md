# Changelog

## 0.3.0 — 2026-09-06

- Increase the building limit to 500 million pixels and remove the 8192-pixel
  side restriction; a 10 km × 10 km area at 0.5 m/pixel fits in one job.
- Use temporary disk-backed arrays for large raster preparation and predictions.
- Filter in blocks with five-pixel halos and polygonise a stitched disk raster.
- Check temporary disk capacity and clean up scratch files after cancellation.
- Add exact-limit, disk-path and filter-seam regression tests, plus a synthetic
  500-million-pixel capacity harness.

## Repository setup

- Add contributor guidance, issue and pull-request templates, and automated
  unit-test and plugin-package checks.
- Add repository navigation and upstream project links to QGIS metadata.

## 0.2.0 — 2026-09-06

- Add local RAMP building detection with overlapping metric tiles, no-data
  handling, minimum-area filtering and GeoPackage export.
- Record class, model, area and review metadata on building results.
- Reuse SAM capture embeddings for repeated interactive prompts.
- Improve cancellation and empty-result handling.
- Publish the original project source under the MIT licence.

## 0.1.0 — 2026-09-06

- Add local SAM point, box and automatic unlabelled-mask segmentation.
- Add georeferenced raster captures, polygon refinement and GeoPackage export.
- Isolate AI dependencies in an external Python environment.
