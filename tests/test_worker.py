import unittest
import tempfile
from pathlib import Path
import numpy as np
from geo_segment.worker import vectorise, validate_request, prepare_predictor


class WorkerTests(unittest.TestCase):
    def request(self):
        return dict(bounds=[100, 200, 110, 210], width=10, height=10, mode='prompt',
                    model_type='vit_b', device='cpu', score_threshold=0.8,
                    min_pixels=1, points_per_side=8, points=[[2, 2]], labels=[1])

    def test_holes_components_and_map_bounds(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[1:6, 1:6] = True
        mask[2:4, 2:4] = False
        mask[8:10, 8:10] = True
        result = vectorise([dict(segmentation=mask, predicted_iou=0.9)], np.ones_like(mask), self.request())
        polygons = result[0]['geometry']['coordinates']
        self.assertEqual(len(polygons), 2)
        self.assertEqual(sorted(len(p) for p in polygons), [1, 2])
        self.assertEqual(result[0]['properties']['pixels'], 25)
        xs = [x for p in polygons for ring in p for x, y in ring]
        ys = [y for p in polygons for ring in p for x, y in ring]
        self.assertEqual((min(xs), max(xs), min(ys), max(ys)), (101, 110, 200, 209))

    def test_nodata_excluded_and_minimum_applied_after_masking(self):
        mask = np.ones((10, 10), dtype=bool)
        valid = np.zeros_like(mask)
        valid[0, 0] = True
        request = self.request()
        request['min_pixels'] = 2
        self.assertEqual(vectorise([dict(segmentation=mask, predicted_iou=1)], valid, request), [])

    def test_diagonal_pixels_remain_separate_valid_components(self):
        mask = np.eye(10, dtype=bool)
        result = vectorise([dict(segmentation=mask, predicted_iou=0.9)], np.ones_like(mask), self.request())
        self.assertEqual(len(result[0]['geometry']['coordinates']), 10)

    def test_invalid_prompt_contracts(self):
        for changes in ({'labels': [0]}, {'labels': []}, {'points': [[10, 5]]},
                        {'box': [4, 4, 3, 8]}, {'device': 'bad'}, {'score_threshold': 1.1}):
            with self.assertRaises(ValueError):
                validate_request(dict(self.request(), **changes))
        validate_request(dict(self.request(), mode='automatic', points=[], labels=[]))

    def test_embedding_cache_reuses_pixels_but_invalidates_changed_image_or_model(self):
        import torch
        class Predictor:
            device = 'cpu'
            calls = 0
            def set_image(self, rgb):
                self.calls += 1
                self.features = torch.ones((1, 256, 64, 64))
                self.original_size = rgb.shape[:2]
                self.input_size = (1024, 1024)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'test.pth'; checkpoint.write_bytes(b'one')
            cache = Path(directory)/'embedding.npz'
            request = dict(checkpoint=str(checkpoint), model_type='vit_b', embedding_cache=str(cache))
            rgb = np.zeros((10, 10, 3), dtype=np.uint8)
            predictor = Predictor()
            self.assertFalse(prepare_predictor(predictor, rgb, request))
            fresh = Predictor()
            self.assertTrue(prepare_predictor(fresh, rgb, request))
            self.assertEqual(fresh.calls, 0)
            self.assertTrue(fresh.is_image_set)
            rgb[0, 0, 0] = 1
            self.assertFalse(prepare_predictor(fresh, rgb, request))
            checkpoint.write_bytes(b'different model')
            self.assertFalse(prepare_predictor(fresh, rgb, request))
            cache.write_bytes(b'interrupted cache')
            self.assertFalse(prepare_predictor(fresh, rgb, request))


if __name__ == '__main__':
    unittest.main()
