"""Local RAMP building inference. No QGIS or SAM imports are required."""
import hashlib
import math
from pathlib import Path

MODEL_SHA256 = "29709ab0ed665f239e60ff2f5dbdcc70bdcb3d2d045a8934387a9bab279d5554"
RESOLUTION = 0.5  # Metres, from the tested RAMP model's embedded metadata.
TILE_SIZE = 256
STRIDE = 192
MAX_PIXELS = 16_000_000


def validate_request(request):
    bounds = request.get("bounds", [])
    if (len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError("Choose a non-empty building detection area.")
    area = request.get("min_area_m2", 10)
    if not math.isfinite(area) or not 0 < area <= 1_000_000:
        raise ValueError("Minimum building area must be between 0 and 1,000,000 m².")
    if not Path(request.get("source", "")).is_file():
        raise ValueError("Building detection needs a local RGB raster file.")
    if not Path(request.get("building_model", "")).is_file():
        raise ValueError("Choose the RAMP XUnet ONNX building model in Settings.")


def grid(bounds):
    """Snap to a stable metric grid, so panning does not change pixel alignment."""
    xmin, ymin, xmax, ymax = bounds
    xmin = math.floor(xmin / RESOLUTION) * RESOLUTION
    ymax = math.ceil(ymax / RESOLUTION) * RESOLUTION
    width = math.ceil((xmax - xmin) / RESOLUTION)
    height = math.ceil((ymax - ymin) / RESOLUTION)
    if width * height > MAX_PIXELS or max(width, height) > 8192:
        raise ValueError("This area is too large for one job. Zoom in (maximum 16 million pixels at 0.5 m).")
    return xmin, ymax, width, height


def to_rgb8(data, valid):
    """Preserve byte RGB; stretch higher-bit data using valid pixels only."""
    import numpy as np
    if not valid.any():
        raise ValueError("No valid RGB imagery intersects the selected area.")
    if data.dtype == np.uint8:
        result = data.copy()
    else:
        result = np.zeros(data.shape, dtype=np.uint8)
        for i, band in enumerate(data):
            low, high = np.percentile(band[valid], (2, 98))
            if high > low:
                result[i] = np.nan_to_num(np.clip((band - low) * (255 / (high - low)), 0, 255)).astype(np.uint8)
    result[:, ~valid] = 0
    return result


def read_area(request):
    import numpy as np
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_bounds, Resampling
    target = CRS.from_wkt(request["crs_wkt"])
    epsg = target.to_epsg()
    if epsg is None or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760):
        raise ValueError("Building jobs must use a local UTM coordinate system in metres.")
    with rasterio.open(request["source"]) as source:
        if source.crs is None or source.count < 3:
            raise ValueError("Building detection needs a georeferenced raster with red, green and blue as its first three bands.")
        footprint = transform_bounds(source.crs, target, *source.bounds, densify_pts=21)
        b = request["bounds"]
        intersection = [max(b[0], footprint[0]), max(b[1], footprint[1]),
                        min(b[2], footprint[2]), min(b[3], footprint[3])]
        if intersection[0] >= intersection[2] or intersection[1] >= intersection[3]:
            raise ValueError("The current view does not intersect the selected raster.")
        xmin, ymax, width, height = grid(intersection)
        transform = from_origin(xmin, ymax, RESOLUTION, RESOLUTION)
        # A virtual warp reads only this bounded area rather than the whole survey.
        has_alpha = rasterio.enums.ColorInterp.alpha in source.colorinterp
        with WarpedVRT(source, crs=target, transform=transform, width=width, height=height,
                       resampling=Resampling.bilinear, add_alpha=not has_alpha) as warped:
            data = warped.read([1, 2, 3])
            valid = (warped.dataset_mask() > 0) & np.isfinite(data).all(axis=0)
        return to_rgb8(data, valid), valid, transform, target


def tiled_mask(rgb, predict, report=lambda message: None):
    """Keep tile cores and polygonise only after stitching, avoiding seam duplicates."""
    import numpy as np
    height, width = rgb.shape[1:]
    rows = max(1, math.ceil((height - TILE_SIZE) / STRIDE) + 1)
    cols = max(1, math.ceil((width - TILE_SIZE) / STRIDE) + 1)
    result = np.zeros((height, width), dtype=np.uint8)
    half = (TILE_SIZE - STRIDE) // 2
    for row in range(rows):
        for col in range(cols):
            y, x = row * STRIDE, col * STRIDE
            h, w = min(TILE_SIZE, height-y), min(TILE_SIZE, width-x)
            tile = np.zeros((1, 3, TILE_SIZE, TILE_SIZE), dtype=np.float32)
            tile[0, :, :h, :w] = rgb[:, y:y+h, x:x+w] / 255.0
            output = predict(tile)
            if output.shape != (1, 2, TILE_SIZE, TILE_SIZE) or not np.isfinite(output).all():
                raise ValueError("The building model returned invalid class scores.")
            # Follow the tested model's metadata threshold, then select the class.
            output[output < 0.2] = 0
            mask = output[0].argmax(axis=0).astype(np.uint8)
            y0, x0 = (half if row else 0), (half if col else 0)
            y1 = h if row == rows-1 else min(h, TILE_SIZE-half)
            x1 = w if col == cols-1 else min(w, TILE_SIZE-half)
            result[y+y0:y+y1, x+x0:x+x1] = mask[y0:y1, x0:x1]
            report("Building tile {} / {}".format(row*cols+col+1, rows*cols))
    return result


def polygons(mask, valid, transform, min_area):
    import numpy as np
    from rasterio.features import shapes
    from shapely.geometry import shape
    mask = ((mask > 0) & valid).astype(np.uint8)
    features = []
    for geometry, value in shapes(mask, mask=mask.astype(bool), transform=transform, connectivity=4):
        if value != 1:
            continue
        area = shape(geometry).area
        if area < min_area:
            continue
        features.append({"geometry": {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]},
                         "properties": {"object_id": len(features)+1, "score": None,
                                        "pixels": round(area / RESOLUTION**2), "class_name": "building",
                                        "model": "RAMP XUnet", "score_type": "not available",
                                        "area_m2": area, "review": "unreviewed"}})
        if len(features) > 20000:
            raise ValueError("More than 20,000 building regions found. Use a smaller area.")
    return features


def run(request, report=print):
    validate_request(request)
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageFilter
    model = Path(request["building_model"])
    digest = hashlib.sha256()
    with model.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError("This release supports the tested RAMP XUnet model only. Use the model linked in README.md.")
    report("Reading local RGB imagery at 0.5 m per pixel…")
    rgb, valid, transform, crs = read_area(request)
    report("Loading the building model on CPU…")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    mask = tiled_mask(rgb, lambda tile: session.run(None, {input_name: tile})[0], report)
    # Embedded RAMP default: 11-pixel median smoothing. Remask no-data afterwards.
    mask = np.array(Image.fromarray(mask).filter(ImageFilter.MedianFilter(11)))
    features = polygons(mask, valid, transform, request.get("min_area_m2", 10))
    height, width = valid.shape
    return {"protocol": 1, "crs_wkt": request["crs_wkt"], "features": features,
            "bounds": [transform.c, transform.f-height*RESOLUTION,
                       transform.c+width*RESOLUTION, transform.f],
            "width": width, "height": height, "pixel_size": RESOLUTION,
            "mode": "buildings", "device": "cpu", "model_sha256": MODEL_SHA256,
            "valid_pixels": int(valid.sum())}
