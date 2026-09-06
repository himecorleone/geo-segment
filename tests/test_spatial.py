import unittest
from geo_segment.spatial import map_to_pixel, pixel_to_map, map_box_to_pixel


class CoordinateTests(unittest.TestCase):
    def test_north_up_and_full_extent_edges(self):
        bounds = [100, 200, 500, 400]
        self.assertEqual(pixel_to_map(0, 0, bounds, 400, 200), [100, 400])
        self.assertEqual(pixel_to_map(400, 200, bounds, 400, 200), [500, 200])
        self.assertEqual(map_to_pixel(300, 300, bounds, 400, 200), [200, 100])
        self.assertEqual(map_to_pixel(500, 200, bounds, 400, 200), [399, 199])

    def test_negative_and_geographic_coordinates(self):
        bounds = [-1, 50, 1, 51]
        point = pixel_to_map(200.5, 100.5, bounds, 1000, 500)
        pixel = map_to_pixel(*point, bounds, 1000, 500)
        self.assertAlmostEqual(pixel[0], 200.5)
        self.assertAlmostEqual(pixel[1], 100.5)

    def test_box_y_inversion(self):
        self.assertEqual(map_box_to_pixel([20, 10, 80, 70], [0, 0, 100, 100], 100, 100), [20, 30, 80, 90])

    def test_bad_prompts_are_rejected(self):
        for point in ((-1, 50), (101, 0), (50, float('nan'))):
            with self.assertRaises(ValueError):
                map_to_pixel(*point, [0, 0, 100, 100], 100, 100)
        with self.assertRaises(ValueError):
            map_box_to_pixel([10, 10, 10, 50], [0, 0, 100, 100], 100, 100)


if __name__ == '__main__':
    unittest.main()
