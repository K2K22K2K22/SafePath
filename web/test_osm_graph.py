import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from Model.utils.osm_graph import (
    RoadDataUnavailable,
    _build_graph_from_xml,
    _fetch_osm_xml,
    _nearest_candidates,
    _overpass_query,
    _prepared_hostname,
    _validated_osm_url,
)
from Model.utils.road_graph import RoadGraph

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


@override_settings(
    SAFEPATH_OSM_API_URL="https://road-provider.internal/api/interpreter",
    SAFEPATH_OSM_API_ALLOWED_HOSTS=("road-provider.internal",),
)
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

    @override_settings(
        SAFEPATH_MAX_SNAP_DISTANCE_METERS=120,
        SAFEPATH_SNAP_CANDIDATE_LIMIT=2,
    )
    def test_endpoint_snapping_uses_nearest_nodes_within_limit(self):
        graph = RoadGraph()
        graph.add_node("near", 0.0, 0.0)
        graph.add_node("also-near", 0.0, 0.001)
        graph.add_node("far", 0.0, 0.01)

        candidates = _nearest_candidates(graph, 0.0, 0.0)

        self.assertEqual([node_id for node_id, _ in candidates], ["near", "also-near"])
        self.assertEqual(_nearest_candidates(graph, 1.0, 1.0), ())

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

    def test_rejects_partial_osm_remark_response(self):
        document = b"""<?xml version="1.0"?>
<osm version="0.6">
  <remark>runtime error: Query run out of memory</remark>
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

    def test_rejects_non_utf8_xml_entity_declarations(self):
        document = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE osm [<!ENTITY test "value">]>
<osm version="0.6" />
""".encode("utf-16")

        with self.assertRaises(RoadDataUnavailable):
            _build_graph_from_xml(document)

    def test_rejects_bomless_utf16_xml_entity_declarations(self):
        document = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE osm [<!ENTITY test "VALUE">]>
<osm version="0.6">
  <node id="&test;" lat="28.4750" lon="77.4770" />
</osm>
"""

        for encoding in ("utf-16-be", "utf-16-le"):
            with self.subTest(encoding=encoding):
                with self.assertRaises(RoadDataUnavailable):
                    _build_graph_from_xml(document.encode(encoding))

    @override_settings(SAFEPATH_OSM_API_MAX_XML_ELEMENTS=3)
    def test_enforces_aggregate_xml_element_limit_across_documents(self):
        document = b"""<osm version="0.6">
  <node id="1" lat="28.4750" lon="77.4770" />
</osm>
"""

        with self.assertRaisesRegex(RoadDataUnavailable, "element limit"):
            _build_graph_from_xml([document, document])

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

    @override_settings(
        SAFEPATH_OSM_API_URL="https://road-provider.internal:invalid/api/interpreter"
    )
    def test_rejects_invalid_provider_port(self):
        with self.assertRaises(RoadDataUnavailable):
            _validated_osm_url()

    @override_settings(SAFEPATH_OSM_API_URL="https://example.com/api/map")
    def test_rejects_provider_host_outside_allowlist(self):
        with self.assertRaises(RoadDataUnavailable):
            _validated_osm_url()

    @override_settings(
        SAFEPATH_PRODUCTION_MODE=False,
        SAFEPATH_OSM_API_URL="https://overpass-api.de/api/interpreter",
        SAFEPATH_OSM_API_ALLOWED_HOSTS=("overpass-api.de",),
    )
    def test_allows_public_provider_in_debug(self):
        self.assertEqual(
            _validated_osm_url(),
            "https://overpass-api.de/api/interpreter",
        )

    def test_rejects_public_provider_in_production(self):
        for host in (
            "api.spainip.es",
            "maps.mail.ru",
            "overpass-api.de",
            "overpass-api.openhistoricalmap.org",
            "overpass.nextgis.com",
            "ovp.dresel.systems",
        ):
            with self.subTest(host=host):
                with override_settings(
                    SAFEPATH_PRODUCTION_MODE=True,
                    SAFEPATH_OSM_API_URL=f"https://{host}/api/interpreter",
                    SAFEPATH_OSM_API_ALLOWED_HOSTS=(host,),
                    SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=(host,),
                ):
                    with self.assertRaisesRegex(
                        RoadDataUnavailable,
                        "paid or self-hosted",
                    ):
                        _validated_osm_url()

    @override_settings(
        SAFEPATH_PRODUCTION_MODE=True,
        SAFEPATH_OSM_API_URL="https://road-provider.internal/api/interpreter",
        SAFEPATH_OSM_API_ALLOWED_HOSTS=("road-provider.internal",),
        SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("road-provider.internal",),
    )
    def test_accepts_private_provider_in_production(self):
        self.assertEqual(
            _validated_osm_url(),
            "https://road-provider.internal/api/interpreter",
        )

    @override_settings(
        SAFEPATH_PRODUCTION_MODE=True,
        SAFEPATH_OSM_API_URL="https://overpass.unlisted.example/api/interpreter",
        SAFEPATH_OSM_API_ALLOWED_HOSTS=("overpass.unlisted.example",),
        SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=(),
    )
    def test_rejects_unapproved_provider_in_production(self):
        with self.assertRaisesRegex(RoadDataUnavailable, "explicitly approved"):
            _validated_osm_url()

    @override_settings(
        SAFEPATH_PRODUCTION_MODE=True,
        SAFEPATH_OSM_API_URL="https://overpass-api.de./api/interpreter",
        SAFEPATH_OSM_API_ALLOWED_HOSTS=("overpass-api.de.",),
        SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("overpass-api.de.",),
    )
    def test_rejects_public_provider_trailing_dot_in_production(self):
        with self.assertRaisesRegex(RoadDataUnavailable, "paid or self-hosted"):
            _validated_osm_url()

    def test_canonicalizes_provider_host_case_and_idna(self):
        with override_settings(
            SAFEPATH_PRODUCTION_MODE=True,
            SAFEPATH_OSM_API_URL="https://ROAD-PROVIDER.INTERNAL/api/interpreter",
            SAFEPATH_OSM_API_ALLOWED_HOSTS=("road-provider.internal",),
            SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("ROAD-PROVIDER.INTERNAL",),
        ):
            self.assertEqual(
                _validated_osm_url(),
                "https://ROAD-PROVIDER.INTERNAL/api/interpreter",
            )

        with override_settings(
            SAFEPATH_PRODUCTION_MODE=True,
            SAFEPATH_OSM_API_URL="https://xn--mnchen-3ya.example/api/interpreter",
            SAFEPATH_OSM_API_ALLOWED_HOSTS=("münchen.example",),
            SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("münchen.example",),
        ):
            self.assertEqual(
                _validated_osm_url(),
                "https://xn--mnchen-3ya.example/api/interpreter",
            )

        with override_settings(
            SAFEPATH_PRODUCTION_MODE=True,
            SAFEPATH_OSM_API_URL="https://ς.gr/api/interpreter",
            SAFEPATH_OSM_API_ALLOWED_HOSTS=("xn--3xa.gr",),
            SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("ς.gr",),
        ):
            self.assertEqual(
                _validated_osm_url(),
                "https://ς.gr/api/interpreter",
            )
            self.assertEqual(
                _prepared_hostname("https://ς.gr/api/interpreter"),
                "xn--3xa.gr",
            )

        with override_settings(
            SAFEPATH_PRODUCTION_MODE=True,
            SAFEPATH_OSM_API_URL="https://ß.gr/api/interpreter",
            SAFEPATH_OSM_API_ALLOWED_HOSTS=("xn--zca.gr",),
            SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS=("ß.gr",),
        ):
            self.assertEqual(
                _validated_osm_url(),
                "https://ß.gr/api/interpreter",
            )
            self.assertEqual(
                _prepared_hostname("https://ß.gr/api/interpreter"),
                "xn--zca.gr",
            )

    def test_builds_bounded_overpass_query(self):
        query = _overpass_query((77.475, 28.474, 77.477, 28.476))

        self.assertIn("[out:xml][timeout:25][maxsize:268435456];", query)
        self.assertIn(
            'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
            'unclassified|residential|living_street|service|road)(_link)?$"]'
            "(28.4740000,77.4750000,28.4760000,77.4770000);",
            query,
        )
        self.assertIn(">;", query)
        self.assertIn("out body;", query)

    def test_provider_request_uses_overpass_query(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"document"]
        response.__enter__.return_value = response

        with patch(
            "Model.utils.osm_graph.requests.get",
            return_value=response,
        ) as get:
            _fetch_osm_xml((77.475, 28.474, 77.477, 28.476))

        params = get.call_args.kwargs["params"]
        self.assertEqual(set(params), {"data"})
        self.assertIn('way["highway"~', params["data"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_provider_requests_are_serialized(self):
        active_requests = 0
        maximum_active_requests = 0
        counter_lock = threading.Lock()

        def provider_response(*args, **kwargs):
            nonlocal active_requests, maximum_active_requests
            with counter_lock:
                active_requests += 1
                maximum_active_requests = max(maximum_active_requests, active_requests)
            time.sleep(0.05)
            with counter_lock:
                active_requests -= 1

            response = MagicMock()
            response.status_code = 200
            response.headers = {}
            response.raise_for_status.return_value = None
            response.iter_content.return_value = [b"document"]
            response.__enter__.return_value = response
            return response

        with patch(
            "Model.utils.osm_graph.requests.get",
            side_effect=provider_response,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _fetch_osm_xml,
                        (77.475 + index, 28.474, 77.477 + index, 28.476),
                    )
                    for index in range(2)
                ]
                for future in futures:
                    future.result()

        self.assertEqual(maximum_active_requests, 1)

    def test_oversized_overpass_request_splits_without_deadlock(self):
        calls = 0

        def provider_response(*args, **kwargs):
            nonlocal calls
            response = MagicMock()
            response.status_code = 400 if calls == 0 else 200
            calls += 1
            response.headers = {}
            response.raise_for_status.return_value = None
            response.iter_content.return_value = [
                b"runtime error: Query exceeded the maximum allowed size"
                if response.status_code == 400
                else b"document"
            ]
            response.__enter__.return_value = response
            return response

        with patch(
            "Model.utils.osm_graph.requests.get",
            side_effect=provider_response,
        ) as get:
            documents = _fetch_osm_xml((77.475, 28.474, 77.477, 28.476))

        self.assertEqual(documents, (b"document", b"document"))
        self.assertEqual(get.call_count, 3)

    def test_persistent_overpass_rejection_fails_without_splitting(self):
        response = MagicMock()
        response.status_code = 400
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"runtime error: invalid query syntax"]
        response.__enter__.return_value = response

        with (
            patch("Model.utils.osm_graph.requests.get", return_value=response) as get,
            self.assertRaises(RoadDataUnavailable),
        ):
            _fetch_osm_xml((77.475, 28.474, 77.477, 28.476))

        get.assert_called_once()

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
