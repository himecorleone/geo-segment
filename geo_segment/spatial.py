"""Dependency-free coordinate contract shared by QGIS, the worker and tests."""
import math


def validate_frame(bounds, width, height):
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
        raise ValueError("Capture bounds must contain four finite coordinates.")
    xmin, ymin, xmax, ymax = bounds
    if xmax <= xmin or ymax <= ymin or width <= 0 or height <= 0:
        raise ValueError("Capture must have positive width and height.")


def map_to_pixel(x, y, bounds, width, height):
    validate_frame(bounds, width, height)
    xmin, ymin, xmax, ymax = bounds
    if not math.isfinite(x) or not math.isfinite(y) or not (xmin <= x <= xmax and ymin <= y <= ymax):
        raise ValueError("Place the prompt inside the captured area.")
    # Prompt centres stay inside the last pixel; polygon edges use the full extent.
    return [min(width - 1, (x - xmin) * width / (xmax - xmin)),
            min(height - 1, (ymax - y) * height / (ymax - ymin))]


def pixel_to_map(x, y, bounds, width, height):
    validate_frame(bounds, width, height)
    xmin, ymin, xmax, ymax = bounds
    return [xmin + x * (xmax - xmin) / width,
            ymax - y * (ymax - ymin) / height]


def map_box_to_pixel(box, bounds, width, height):
    xmin, ymin, xmax, ymax = box
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("Draw a box with positive width and height.")
    left, top = map_to_pixel(xmin, ymax, bounds, width, height)
    right, bottom = map_to_pixel(xmax, ymin, bounds, width, height)
    if right - left < 1 or bottom - top < 1:
        raise ValueError("The box must cover at least one captured pixel in each direction.")
    return [left, top, right, bottom]
