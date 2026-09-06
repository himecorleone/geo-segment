"""Exercise the full 500-million-pixel data path with simulated model scores.

Requires AI/building dependencies and the supported RAMP file for its normal
checksum check. This tests capacity and seams, NOT real model speed or accuracy.
Temporary imagery and intermediate rasters are removed automatically.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from geo_segment.buildings import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=root/'models/ramp_XUnet_256.onnx')
    parser.add_argument('--output', type=Path, default=root/'dist/large-area-test/capacity.json')
    args = parser.parse_args()
    width, height = 25000, 20000
    class SimulatedSession:
        def __init__(self, *args, **kwargs): pass
        def get_inputs(self): return [SimpleNamespace(name='image')]
        def run(self, _, inputs):
            tile = inputs['image'][:, 0]
            return [np.stack([1-tile, tile], axis=1)]
    last_report = [0.0]
    def report(message):
        now = time.monotonic()
        if now-last_report[0] > 5 or '…' in message and 'block' not in message:
            print(message, flush=True)
            last_report[0] = now
    with tempfile.TemporaryDirectory(prefix='geo-segment-capacity-') as directory:
        path = Path(directory)/'synthetic.tif'
        transform = from_origin(600000, 4000000, .5, .5)
        with rasterio.open(path, 'w', driver='GTiff', width=width, height=height,
                           count=3, dtype='uint8', crs='EPSG:32611', transform=transform,
                           tiled=True, compress='lzw', SPARSE_OK=True) as dst:
            for x, y in [(0, 0), (1000, 1000), (9990, 9990)]:
                dst.write(np.full((3, 80, 100), 255, dtype='uint8'), window=Window(x, y, 100, 80))
        request = dict(source=str(path), crs_wkt=rasterio.crs.CRS.from_epsg(32611).to_wkt(),
                       bounds=[600000, 3990000, 612500, 4000000],
                       building_model=str(args.model), min_area_m2=10, work_dir=directory)
        started = time.monotonic()
        with patch('onnxruntime.InferenceSession', SimulatedSession):
            result = run(request, report)
        elapsed = time.monotonic()-started
        assert result['width']*result['height'] == 500_000_000
        assert result['valid_pixels'] == 500_000_000
        assert len(result['features']) == 3
        assert not list(Path(directory).glob('buildings-*'))
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = peak if sys.platform == 'darwin' else peak*1024
        summary = dict(test='500-million-pixel synthetic capacity; simulated model scores',
                       pixels=500_000_000, features=3, elapsed_seconds=elapsed,
                       peak_resident_bytes=peak_bytes, scratch_cleaned=True,
                       real_model_inference=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
