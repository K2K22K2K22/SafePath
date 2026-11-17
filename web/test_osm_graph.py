from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from Model.utils.osm_graph import (
    RoadDataUnavailable,
    _build_graph_from_xml,
    _fetch_osm_xml,
    _validated_osm_url,
)

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

DIRECTION_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="28.4750" lon="77.4770" />
  <node id="2" lat="28.4751" lon="77.4770" />
  <node id="3" lat="28.4752" lon="77.4770" />
  <node id="4" lat="28.4753" lon="77.4770" />
  <node id="5" lat="28.4754" lon="77.4770" />
  <way id="20">
    <nd ref="1" /><nd ref="2" />
    <tag k="highway" v="motorway" />
  </way>
  <way id="21">
    <nd ref="2" /><nd ref="3" />
    <tag k="highway" v="residential" />
    <tag k="junction" v="roundabout" />
  </way>
  <way id="22">
    <nd ref="3" /><nd ref="4" />
    <tag k="highway" v="residential" />
    <tag k="junction" v="roundabout" />
    <tag k="oneway" v="no" />
  </way>
</osm>
"""

ACCESS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="28.4750" lon="77.4770" />
  <node id="2" lat="28.4751" lon="77.4770" />
  <node id="3" lat="28.4752" lon="77.4770" />
  <node id="4" lat="28.4753" lon="77.4770" />
  <way id="30">
    <nd ref="1" /><nd ref="2" />
    <tag k="highway" v="residential" />
    <tag k="access" v="no" />
    <tag k="motorcar" v="yes" />
  </way>
  <way id="31">
    <nd ref="3" /><nd ref="4" />
    <tag k="highway" v="residential" />
    <tag k="access" v="destination" />
  </way>
</osm>
"""

BARRIER_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="28.4750" lon="77.4770" />
  <node id="2" lat="28.4751" lon="77.4770">
    <tag k="barrier" v="bollard" />
  </node>
  <node id="3" lat="28.4752" lon="77.4770" />
  <node id="4" lat="28.4753" lon="77.4770">
    <tag k="barrier" v="gate" />
    <tag k="motorcar" v="yes" />
  </node>
  <way id="40">
    <nd ref="1" /><nd ref="2" />
    <tag k="highway" v="residential" />
  </way>
  <way id="41">
    <nd ref="3" /><nd ref="4" />
    <tag k="highway" v="residential" />
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

    def test_motorway_and_roundabout_default_to_one_way(self):
        graph = _build_graph_from_xml(DIRECTION_FIXTURE)

        self.assertIn("way-20-0", graph.edges)
        self.assertNotIn("way-20-0-reverse", graph.edges)
        self.assertIn("way-21-0", graph.edges)
        self.assertNotIn("way-21-0-reverse", graph.edges)

    def test_explicit_oneway_no_overrides_roundabout_default(self):
        graph = _build_graph_from_xml(DIRECTION_FIXTURE)

        self.assertIn("way-22-0", graph.edges)
        self.assertIn("way-22-0-reverse", graph.edges)

    def test_specific_vehicle_access_overrides_generic_access(self):
        graph = _build_graph_from_xml(ACCESS_FIXTURE)

        self.assertIn("way-30-0", graph.edges)
        self.assertIn("way-30-0-reverse", graph.edges)
        self.assertNotIn("way-31-0", graph.edges)

    def test_node_barrier_blocks_matching_road_segment(self):
        graph = _build_graph_from_xml(BARRIER_FIXTURE)

        self.assertNotIn("way-40-0", graph.edges)
        self.assertIn("way-41-0", graph.edges)

    def test_rejects_partial_osm_error_response(self):
        document = b"""<?xml version="1.0"?>
<osm version="0.6">
  <error>Requested area is too large</error>
</osm>
"""

        with self.assertRaises(RoadDataUnavailable):
            _build_graph_from_xml(document)

    def test_rejects_xml_entity_declarations(self):
        document = b"""<?xml version="1.0"?>
<!DOCTYPE osm [<!ENTITY test "value">]>
<osm version="0.6" />
"""

        with self.assertRaises(RoadDataUnavailable):
            _build_graph_from_xml(document)

    def test_rejects_malformed_drivable_way(self):
        document = b"""<?xml version="1.0"?>
<osm version="0.6">
  <node id="1" lat="28.4750" lon="77.4770" />
  <node id="2" lat="28.4751" lon="77.4770" />
  <way>
    <nd ref="1" /><nd ref="2" />
    <tag k="highway" v="residential" />
  </way>
</osm>
"""

        with self.assertRaises(RoadDataUnavailable):
            _build_graph_from_xml(document)

    @override_settings(SAFEPATH_OSM_API_URL="http://127.0.0.1/api/map")
    def test_rejects_non_https_provider_url(self):
        with self.assertRaises(RoadDataUnavailable):
            _validated_osm_url()

    @override_settings(SAFEPATH_OSM_API_URL="https://example.com/api/map")
    def test_rejects_provider_host_outside_allowlist(self):
        with self.assertRaises(RoadDataUnavailable):
            _validated_osm_url()

    def test_streamed_response_obeys_byte_limit(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"x" * 100]
        response.__enter__.return_value = response

        with (
            patch("Model.utils.osm_graph.requests.get", return_value=response),
            override_settings(SAFEPATH_OSM_API_MAX_BYTES=50),
            self.assertRaises(RoadDataUnavailable),
        ):
            _fetch_osm_xml((0.0, 0.0, 0.01, 0.01))

    def test_provider_redirect_is_rejected_without_following_it(self):
        response = MagicMock()
        response.status_code = 302
        response.__enter__.return_value = response

        with (
            patch("Model.utils.osm_graph.requests.get", return_value=response) as get,
            self.assertRaises(RoadDataUnavailable),
        ):
            _fetch_osm_xml((0.0, 0.0, 0.01, 0.01))

        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
