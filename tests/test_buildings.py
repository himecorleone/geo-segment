import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from geo_segment.buildings import grid, polygons, read_area, tiled_mask, to_rgb8


class BuildingTests(unittest.TestCase):
    def test_overlap_cores_keep_one_building_across_four_tiles(self):
        rgb = np.zeros((3, 400, 400), dtype=np.uint8)
        rgb[:, 160:300, 150:300] = 255
        def predict(tile):
            return np.stack([1-tile[:, 0], tile[:, 0]], axis=1)
        mask = tiled_mask(rgb, predict)
        np.testing.assert_array_equal(mask, rgb[0] > 0)
        features = polygons(mask, np.ones_like(mask, dtype=bool), from_origin(0, 200, .5, .5), 10)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['properties']['area_m2'], 140*150*.25)

    def test_small_edge_tiles_and_invalid_model_output(self):
        rgb = np.full((3, 12, 9), 255, dtype=np.uint8)
        mask = tiled_mask(rgb, lambda t: np.stack([1-t[:, 0], t[:, 0]], axis=1))
        self.assertEqual(int(mask.sum()), 108)
        with self.assertRaises(ValueError):
            tiled_mask(rgb, lambda t: np.full((1, 2, 256, 256), np.nan))

    def test_nodata_splits_regions_and_area_filter_uses_metres(self):
        mask = np.ones((20, 20), dtype=np.uint8)
        valid = np.ones_like(mask, dtype=bool)
        valid[:, 5:7] = False
        features = polygons(mask, valid, from_origin(0, 10, .5, .5), 30)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['properties']['area_m2'], 65)
        self.assertEqual(features[0]['properties']['class_name'], 'building')
        self.assertIsNone(features[0]['properties']['score'])

    def test_grid_alignment_and_size_limit(self):
        self.assertEqual(grid([1.1, 2.1, 4.2, 5.2]), (1.0, 5.5, 7, 7))
        with self.assertRaises(ValueError):
            grid([0, 0, 100000, 100000])

    def test_stretch_excludes_nodata_and_preserves_byte_rgb(self):
        data = np.arange(300, dtype=np.uint16).reshape(3, 10, 10)*10
        valid = np.ones((10, 10), dtype=bool)
        valid[:, :2] = False
        data[:, :, :2] = 65535
        result = to_rgb8(data, valid)
        self.assertEqual(result.dtype, np.uint8)
        self.assertTrue((result[:, :, :2] == 0).all())
        self.assertEqual(int(result.max()), 255)
        np.testing.assert_array_equal(to_rgb8(result, valid), result)
        with self.assertRaises(ValueError):
            to_rgb8(data, np.zeros_like(valid))

    def test_local_raster_alpha_survives_metric_warp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'rgb.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=20, height=20, count=4,
                               dtype='uint8', crs='EPSG:32611', transform=from_origin(600000, 4000000, .5, .5)) as dst:
                data = np.full((4, 20, 20), 255, dtype=np.uint8)
                data[3, :, :5] = 0
                dst.write(data)
                dst.colorinterp = (rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green,
                                   rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha)
            crs = rasterio.crs.CRS.from_epsg(32611).to_wkt()
            rgb, valid, transform, _ = read_area(dict(source=str(path), crs_wkt=crs,
                bounds=[600000, 3999990, 600010, 4000000]))
            self.assertEqual(valid.sum(), 300)
            self.assertTrue((rgb[:, :, :5] == 0).all())
            with self.assertRaisesRegex(ValueError, 'does not intersect'):
                read_area(dict(source=str(path), crs_wkt=crs, bounds=[0, 0, 10, 10]))


if __name__ == '__main__':
    unittest.main()
