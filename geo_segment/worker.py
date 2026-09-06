"""One local inference job. JSON on disk, progress on stdout; no QGIS imports."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

try:
    from .spatial import validate_frame
except ImportError:
    from spatial import validate_frame


def progress(message):
    print(message, flush=True)


def check_runtime():
    import numpy
    import torch
    import torchvision
    import rasterio
    from PIL import Image
    from segment_anything import SamPredictor, SamAutomaticMaskGenerator
    return {"python": sys.version.split()[0], "torch": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "mps": bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available()),
            "buildings": all(importlib.util.find_spec(m) is not None for m in ("onnxruntime", "shapely"))}


def prepare_predictor(predictor, rgb, request):
    """Reuse one capture embedding between prompt jobs; models remain isolated."""
    import numpy as np
    import torch
    path = Path(request["embedding_cache"]) if request.get("embedding_cache") else None
    checkpoint = Path(request["checkpoint"]).resolve()
    stamp = checkpoint.stat()
    identity = (str(checkpoint), stamp.st_size, stamp.st_mtime_ns, request["model_type"])
    key = hashlib.sha256(rgb.tobytes() + str(rgb.shape).encode() + repr(identity).encode()).hexdigest()
    if path and path.is_file():
        try:
            with np.load(path, allow_pickle=False) as cache:
                features = cache["features"]
                if (cache["key"].item() == key and features.shape == (1, 256, 64, 64)
                        and features.dtype == np.float32 and np.isfinite(features).all()
                        and tuple(cache["original_size"]) == rgb.shape[:2]):
                    predictor.features = torch.from_numpy(features.copy()).to(predictor.device)
                    predictor.original_size = tuple(int(v) for v in cache["original_size"])
                    predictor.input_size = tuple(int(v) for v in cache["input_size"])
                    predictor.is_image_set = True
                    progress("Reusing this capture's SAM embedding…")
                    return True
        except (OSError, ValueError, KeyError, EOFError):
            pass  # A missing or interrupted cache never prevents fresh inference.
    predictor.set_image(rgb)
    if path:
        temporary = path.with_suffix(".tmp")
        try:
            with temporary.open("wb") as handle:
                np.savez(handle, key=key, features=predictor.features.detach().cpu().float().numpy(),
                         original_size=predictor.original_size, input_size=predictor.input_size)
            os.replace(temporary, path)
        except OSError:
            progress("Embedding cache unavailable; inference can continue without it.")
    return False


def validate_request(request):
    validate_frame(request["bounds"], request["width"], request["height"])
    if request["mode"] not in ("prompt", "automatic"):
        raise ValueError("Unknown segmentation mode.")
    if request["model_type"] not in ("vit_b", "vit_l", "vit_h"):
        raise ValueError("Unsupported SAM model type.")
    if request["device"] not in ("auto", "cpu", "cuda", "mps"):
        raise ValueError("Unsupported compute device.")
    if max(request["width"], request["height"]) > 2048:
        raise ValueError("Capture exceeds the 2048-pixel limit.")
    if not 0 <= request["score_threshold"] <= 1:
        raise ValueError("Quality threshold must be between 0 and 1.")
    if not 1 <= request["points_per_side"] <= 64 or request["min_pixels"] < 1:
        raise ValueError("Invalid mask generation settings.")
    points = request.get("points", [])
    labels = request.get("labels", [])
    if len(points) != len(labels) or any(v not in (0, 1) for v in labels):
        raise ValueError("Each prompt point needs a positive or negative label.")
    for p in points:
        if len(p) != 2 or not all(math.isfinite(v) for v in p):
            raise ValueError("Invalid prompt coordinates.")
        if not (0 <= p[0] < request["width"] and 0 <= p[1] < request["height"]):
            raise ValueError("Prompt is outside the capture.")
    box = request.get("box")
    if box is not None:
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError("Invalid box coordinates.")
        if not (0 <= box[0] < box[2] < request["width"] and
                0 <= box[1] < box[3] < request["height"]):
            raise ValueError("Box is outside the capture or has zero area.")
    if request["mode"] == "prompt" and box is None and 1 not in labels:
        raise ValueError("Add a positive point or a box before segmenting.")


def vectorise(records, valid, request):
    import numpy as np
    from affine import Affine
    from rasterio.features import shapes
    xmin, ymin, xmax, ymax = request["bounds"]
    transform = Affine((xmax - xmin) / request["width"], 0, xmin,
                       0, -(ymax - ymin) / request["height"], ymax)
    features = []
    for object_id, record in enumerate(records, 1):
        mask = np.asarray(record["segmentation"], dtype=bool) & valid
        count = int(mask.sum())
        if count < request["min_pixels"]:
            continue
        polygons = [geometry["coordinates"] for geometry, value in
                    shapes(mask.astype("uint8"), mask=mask, transform=transform,
                           connectivity=4) if value == 1]
        if polygons:
            features.append({"geometry": {"type": "MultiPolygon", "coordinates": polygons},
                             "properties": {"object_id": object_id,
                                            "score": float(record["predicted_iou"]),
                                            "pixels": count, "class_name": "unlabelled",
                                            "model": "SAM " + request.get("model_type", "vit_b"),
                                            "score_type": "predicted mask IoU", "review": "unreviewed"}})
    return features


def run(request):
    if request.get("mode") == "buildings":
        try:
            from .buildings import run as run_buildings
        except ImportError:
            from buildings import run as run_buildings
        return run_buildings(request, progress)
    validate_request(request)
    import numpy as np
    import torch
    from PIL import Image
    from segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator
    checkpoint = Path(request["checkpoint"])
    if not checkpoint.is_file():
        raise ValueError("Choose a downloaded SAM checkpoint in Settings.")
    device = request["device"]
    if device == "auto":
        # CPU is the conservative fallback on macOS; MPS can be selected explicitly.
        device = "cuda" if torch.cuda.is_available() else "cpu"
    progress("Loading the SAM model on " + device + "…")
    # Load the state dict with weights_only to avoid arbitrary checkpoint pickle code.
    model = sam_model_registry[request["model_type"]](checkpoint=None)
    model.load_state_dict(torch.load(str(checkpoint), map_location="cpu", weights_only=True))
    model.to(device=device)
    model.eval()
    with Image.open(request["image"]) as source:
        rgba = np.asarray(source.convert("RGBA"))
    if rgba.shape[:2] != (request["height"], request["width"]):
        raise ValueError("Image dimensions do not match the capture.")
    valid = rgba[:, :, 3] > 0
    if not valid.any():
        raise ValueError("The captured raster contains no visible pixels.")
    for x, y in request.get("points", []):
        if not valid[int(y), int(x)]:
            raise ValueError("A prompt is on transparent/no-data imagery. Move it onto the raster.")
    rgb = np.ascontiguousarray(rgba[:, :, :3])
    rgb[~valid] = 0
    progress("Segmenting the captured imagery…")
    with torch.inference_mode():
        if request["mode"] == "automatic":
            generator = SamAutomaticMaskGenerator(
                model, points_per_side=request["points_per_side"], points_per_batch=16,
                pred_iou_thresh=request["score_threshold"], stability_score_thresh=0.90,
                crop_n_layers=0, output_mode="binary_mask")
            records = generator.generate(rgb)
        else:
            predictor = SamPredictor(model)
            prepare_predictor(predictor, rgb, request)
            points = request.get("points", [])
            box = request.get("box")
            masks, scores, _ = predictor.predict(
                point_coords=np.asarray(points, dtype=np.float32) if points else None,
                point_labels=np.asarray(request["labels"], dtype=np.int32) if points else None,
                box=np.asarray(box, dtype=np.float32) if box else None,
                multimask_output=True)
            index = int(np.argmax(scores))
            records = ([{"segmentation": masks[index], "predicted_iou": float(scores[index])}]
                       if scores[index] >= request["score_threshold"] else [])
    if len(records) > 2000:
        raise ValueError("More than 2,000 masks found. Use a smaller capture or raise the quality threshold.")
    progress("Converting masks to georeferenced polygons…")
    features = vectorise(records, valid, request)
    return {"protocol": 1, "crs_wkt": request["crs_wkt"], "bounds": request["bounds"],
            "features": features, "device": device, "mode": request["mode"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.check:
            progress(json.dumps(check_runtime()))
            return 0
        if not args.request or not args.output:
            parser.error("--request and --output are required")
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = run(request)
        output = Path(args.output)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        os.replace(temporary, output)
        progress("Finished: " + str(len(result["features"])) + " objects.")
        return 0
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
