from django.test import SimpleTestCase

from Model.utils.osm_graph import _build_graph_from_xml

OSM_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="28.4750" lon="77.4770" />
  <node id="2" lat="28.4759" lon="77.4770" />
  <node id="3" lat="28.4759" lon="77.4780" />
  <way id="10">
    <nd ref="1" />
    <nd ref="2" />
    <tag k="highway" v="residential" />
    <tag k="name" v="Test Road" />
  </way>
  <way id="11">
    <nd ref="2" />
    <nd ref="3" />
    <tag k="highway" v="residential" />
    <tag k="oneway" v="yes" />
  </way>
  <way id="12">
    <nd ref="1" />
    <nd ref="2" />
    <tag k="highway" v="footway" />
  </way>
</osm>
"""


class OSMGraphTests(SimpleTestCase):
    def test_builds_directed_edges_with_geometry_and_metadata(self):
        graph = _build_graph_from_xml(OSM_FIXTURE)

        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(len(graph.edges), 3)
        forward = graph.edges["way-10-0"]
        reverse = graph.edges["way-10-0-reverse"]
        self.assertEqual(forward.source, "1")
        self.assertEqual(forward.target, "2")
        self.assertEqual(reverse.source, "2")
        self.assertEqual(reverse.target, "1")
        self.assertGreater(forward.distance_meters, 90)
        self.assertEqual(forward.metadata["name"], "Test Road")
        self.assertEqual(len(forward.geometry), 2)

    def test_excludes_non_drivable_ways(self):
        graph = _build_graph_from_xml(OSM_FIXTURE)

        self.assertNotIn("way-12-0", graph.edges)
        self.assertNotIn("way-12-0-reverse", graph.edges)

    def test_one_way_creates_only_forward_edge(self):
        graph = _build_graph_from_xml(OSM_FIXTURE)

        self.assertIn("way-11-0", graph.edges)
        self.assertNotIn("way-11-0-reverse", graph.edges)
