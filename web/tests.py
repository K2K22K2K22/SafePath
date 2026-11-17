import math

from django.test import SimpleTestCase

from Model.utils.geometry_utils import haversine


class GeometryTests(SimpleTestCase):
    def test_haversine_returns_metres(self):
        distance = haversine(28.475, 77.477, 28.476, 77.477)

        self.assertGreater(distance, 100)
        self.assertLess(distance, 120)
        self.assertTrue(math.isfinite(distance))
