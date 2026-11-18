# SAFE PATH Improvement Roadmap

> Status: completed implementation record. This document preserves the audit and plan from 17 November 2026. References to removed DeepSeek, OSRM, and legacy graph components describe the audited starting point, not the current application. See [ARCHITECTURE.md](ARCHITECTURE.md) and the project [README](../README.md) for current behavior.

## 1. Purpose and scope

This roadmap records the repository audit completed on 17 November 2026. It converts the requested improvement programme into an incremental implementation plan based on the code that is currently present.

The project will remain a Django application. It is an enhancement of the existing application, not a rewrite. The routing, map, data, and UI work will replace incomplete implementations while preserving working Django, Leaflet, Docker, and static asset conventions.

No deep learning, FDL functionality, or replacement LLM provider will be introduced.

## 2. Audit summary

### 2.1 Repository state

- Branch: `main`, clean working tree at audit start.
- Latest commit: `ef19c86 Add issue templates for bug report and feature request`.
- No uncommitted user changes were present when the audit began.
- Python and Django are the primary backend technologies.
- The frontend is a server-rendered Django template with Leaflet and one static JavaScript file.
- The configured database is SQLite, although the README claims PostgreSQL and PostGIS.
- FastAPI is installed but no FastAPI application or route exists.
- Tailwind CSS is not installed or loaded, although the README claims it is used.
- No CI workflow, lint configuration, frontend package manifest, `.env.example`, or `.dockerignore` exists.
- `web/tests.py` contains no tests, so `python manage.py test` currently runs zero tests.

### 2.2 Current request flow

```text
Browser
  -> Django template
  -> Leaflet map and browser geocoding
  -> GET /api/safe-route/
  -> OSRM public route service
  -> CSV incident loading
  -> DeepSeek risk request for each segment
  -> custom graph and A*-named function
  -> one route response
  -> Leaflet polyline
```

### 2.3 Current implementation inventory

| Area | Current implementation | Assessment |
|---|---|---|
| Web entry point | `web/templates/web/home.html`, `web/views.py` | Functional server-rendered page |
| API | `Model/views.py`, `safepath_backend/urls.py` | One DRF endpoint with no input validation |
| Map | Leaflet 1.9.4 loaded from a CDN | Basic map and markers |
| Route source | `Model/utils/osrm_client.py` | Uses one public OSRM route response |
| Graph | `Model/utils/safety_graph.py` | Builds a small bidirectional graph from one route polyline |
| Search | `Model/utils/safety_astar.py` | Dijkstra-style search with no A* heuristic |
| Risk data | `data/delhi_crime_data.csv` | 225 static rows with coordinates and severity |
| Risk scoring | `Model/utils/crime_scoring.py` | Calls DeepSeek for segment risk |
| LLM client | `Model/utils/deepseek_client.py` | Active DeepSeek integration |
| Frontend state | `web/static/web/js/script.js` | Single global script with map and route state |
| Styling | `web/static/web/css/style.css` | Custom CSS, fixed dimensions, dark-only appearance |
| Theme | None | No theme state or persistence |
| Heatmap | None | No layer, control, or incident heat endpoint |
| Authentication | Django authentication framework only | No custom login, registration, or account UI |
| Reporting | None | No incident or user-report model, form, or API |
| Deployment | `Dockerfile`, `docker-compose.yml` | Single Django development container |

## 3. Problems identified

### 3.1 Routing and graph correctness

1. `safe_a_star` does not use an A* heuristic. It is a priority-queue shortest-path implementation that is equivalent to Dijkstra.
2. No Dijkstra implementation exists separately for the minimum-distance objective.
3. The graph is built from one OSRM response. It represents the returned route, not the surrounding road network, so it cannot discover an alternative path.
4. Every graph edge is made bidirectional. This does not preserve OSM one-way restrictions.
5. The risk penalty adds a dimensionless value to distance in metres. The maximum possible penalty is three metres, so risk has negligible influence on route choice.
6. The selected route and the original route are identical in normal operation because the graph contains only that path.
7. Unreachable goals cause an uncaught `KeyError` during path reconstruction.
8. The response distance sums haversine distances between overview polyline vertices. OSRM reported 43,454.6 metres for the audit route while the application reported 43,469.1 metres.
9. The response has no algorithm identifier, path cost, nodes explored, computation time, route objective, or route diversity data.

### 3.2 Risk and data correctness

1. DeepSeek is called once per segment, making cost and latency dependent on an external LLM.
2. Without a DeepSeek key, every segment receives a constant fallback risk of `0.2`. With a key, route selection can change between identical requests.
3. `geometry_utils.haversine` returns kilometres, but `crime_scoring` compares that value with a radius of `200`. The intended 200 metre radius is effectively 200 kilometres.
4. The CSV is static and its provenance is undocumented. It contains 225 rows, 44 duplicate coordinate pairs, mixed category levels, and locations within a Delhi bounding box.
5. The README describes real-time crime data, user reports, and police APIs. None of these live sources is implemented.
6. No route metric distinguishes no incident coverage from an incident-free road.

### 3.3 Frontend correctness and maintainability

1. The script ends by reading `fromLoc`, `startIcon`, and `endIcon` outside their scope. This raises a `ReferenceError` during page load and prevents reliable use of the interface.
2. Route cards contain hard-coded names, safety ratings, and journey times. They are not connected to API results.
3. Duplicate HTML IDs are used for `directions-btn` and `file`.
4. The map has a fixed width of 1450 pixels and does not adapt to smaller screens.
5. Only one visible route can be drawn. The original route is added with zero opacity.
6. No reusable route card, comparison table, button, badge, or input component exists.
7. The custom CSS contains repeated style blocks and no shared design tokens.
8. No loading, empty, or validation state is consistently presented.
9. The map uses one fixed tile layer and does not follow an application theme.
10. Browser geocoding calls Nominatim directly without a timeout, request policy identifier, or server-side proxy.

### 3.4 API, security, and deployment gaps

1. Missing or non-numeric route parameters cause a `TypeError` and a 500 response.
2. `/api/test-deepseek/` references an undefined `test_deepseek` function and returns a 500 response.
3. External requests do not check status codes or use timeouts consistently.
4. `SECRET_KEY` is committed in source, `DEBUG` is always true, and `ALLOWED_HOSTS` is empty.
5. Docker copies the full development server configuration and has no health check.
6. The Docker build has no `.dockerignore`, so local environments and caches can be copied into images.
7. No test, CI, formatting, lint, or deployment verification workflow exists.

## 4. Target architecture

```text
Django templates and reusable partials
  -> shared browser API and map modules
  -> Leaflet route layers, markers, heat layer, and theme-aware tiles

Django REST Framework route view
  -> route service
     -> OSM road graph loader and cache
     -> deterministic incident risk model
     -> custom Dijkstra implementation
     -> custom modified A* implementation
     -> alternative candidate and diversity filter
  -> structured route response

Bundled incident CSV
  -> validated incident loader
  -> edge risk calculation
  -> heatmap point endpoint
```

### 4.1 Frontend architecture decision

The repository has no React application or frontend build. Converting the project to React would create a second application model and violate the requirement to avoid a rewrite.

The frontend will therefore retain Django templates, Leaflet, and native browser JavaScript. Repeated route cards and comparison rows will use reusable Django template partials and shared rendering functions. Tailwind utility classes will replace repeated custom layout and component styles. Leaflet-specific styling will remain in a small CSS layer.

This decision preserves the existing architecture while meeting the reusable-component and Tailwind requirements in the context of the actual codebase.

### 4.2 Road graph source

No road database or road graph exists in the repository. A bounded Overpass-compatible read-only provider will return OSM road data for the requested route area. A small XML parser will convert drivable OSM ways into the project's directed graph. The custom routing engine will not use an external routing algorithm.

The provider interface remains Overpass-compatible so deployments can use a paid or self-hosted instance instead of a public endpoint. Public Overpass instances are development fallbacks only because they provide no availability guarantee. The road-data route is cached, uses bounded serialized requests, and avoids adding a large geospatial runtime dependency.

The custom routing engine will operate on the resulting directed, weighted graph:

- Nodes are OSM road vertices.
- Edges are directed OSM road segments.
- Edge length is the geodesic distance between consecutive endpoints in metres.
- Edge geometry stores the segment between consecutive OSM nodes.
- Edge metadata retains road class, name, one-way information, and available travel-time data.
- Origin and destination are snapped to nearby routable nodes within configured limits; snap distances are not returned by the API.
- Graphs are cached in process by normalised bounding box and time window.
- Request timeouts and upstream errors produce explicit 4xx or 503 responses.

The route area is the bounding box of the requested points plus a configurable road-network margin. If either snapped node is outside the loaded area or too far from the requested point, the loader expands the area and retries.

### 4.3 Risk model

Risk will be deterministic and based only on the bundled incident records.

For each road edge and incident:

1. Measure the shortest distance from the incident coordinate to the stored edge segment in metres.
2. Apply a documented incident influence radius of 200 metres.
3. Weight the incident by normalised severity, from 1 to 5, mapped to 0.2 to 1.0.
4. Apply distance decay within the influence radius.
5. Sum the contributions for all nearby incidents.
6. Convert the bounded exposure to edge risk in the range 0 to 1.

Route risk will be the length-weighted mean edge risk. The API safety score will be the inverse risk score on a 0 to 100 scale, presented in the interface as a record score. Risk level thresholds and the exact formula will be documented with the implementation.

A route that is not fully covered by the incident dataset will report unknown safety. The interface will present that route as unrated instead of claiming that it is proven safe.

### 4.4 Dijkstra and modified A* objectives

Dijkstra will use the directed graph edge length as its only cost. It will return the minimum-distance path and the exact sum of the selected edge lengths.

Modified A* will use this transparent edge cost:

```text
edge_cost = distance_m + beta * risk * distance_m
```

The distance term remains in metres. The risk term is a proportional penalty, so its effect is independent of the edge-length unit. `beta` is zero for a pure distance objective, moderate for a balanced objective, and substantially larger for the safety objective.

The A* heuristic will be straight-line distance in metres to the goal. It is admissible because every edge cost is at least its edge length and the risk penalty is non-negative.

The initial weights will be defined as named constants and documented with their rationale:

- Balanced: `beta = 2.0`.
- Safest: `beta = 8.0`.

Tests will establish that the safety objective materially changes route selection on a graph where a lower-risk route is longer. The constants can then be tuned only with documented evidence and regression coverage.

### 4.5 Alternative route generation

The route service will generate a bounded candidate set using the same graph and the two permitted algorithms:

1. Run Dijkstra for the shortest route.
2. Run modified A* for the safest and balanced objectives.
3. Re-run each objective with temporary penalties on edges used by already selected routes.
4. Rank candidates by their stated objective.
5. Remove exact duplicates by edge sequence.
6. Measure shared interior edges after trimming the common start and end sections.
7. Reject a candidate when its trimmed edge overlap exceeds the documented diversity threshold, unless no other valid path exists.
8. Return up to four distinct routes.

A route that is both shortest and safest will carry both objective labels in one route object. The API and UI will not return duplicate geometry merely to fill a fixed card count.

The diversity threshold will be documented and tested. It will be applied after common start and end edges are removed so unavoidable connector roads do not incorrectly make an otherwise different route a duplicate.

### 4.6 Distance and travel time

- Distance is the sum of the lengths of the exact graph edges in the selected path.
- Kilometres are presentation values derived from metres, never a separate calculation.
- Geometry uses the backend edge geometry and retains intermediate points.
- Travel time uses OSM `maxspeed` values when available and documented road-class fallback speeds otherwise.
- The response will identify travel time as estimated and include its source.

## 5. Planned API changes

### 5.1 Route endpoint

`GET /api/routes/` will replace the current response shape. `/api/safe-route/` may remain as a compatibility alias that calls the same view, with no separate business logic.

Query parameters:

| Parameter | Validation |
|---|---|
| `start_lat` | Required decimal latitude from -90 to 90 |
| `start_lon` | Required decimal longitude from -180 to 180 |
| `end_lat` | Required decimal latitude from -90 to 90 |
| `end_lon` | Required decimal longitude from -180 to 180 |

Response fields:

```json
{
  "origin": {"lat": 28.4748, "lon": 77.4764},
  "destination": {"lat": 28.6139, "lon": 77.209},
  "routes": [
    {
      "id": "route-id",
      "type": "safest",
      "labels": ["safest", "shortest"],
      "algorithm": "modified_astar",
      "cost_function": {"beta": 8.0},
      "node_ids": [],
      "edge_ids": [],
      "geometry": [[28.4748, 77.4764]],
      "distance_meters": 43454.6,
      "distance_km": 43.4546,
      "duration_seconds": 2812.5,
      "duration_source": "estimated_from_road_data",
      "risk_score": 0.18,
      "safety_score": 82,
      "risk_level": "low",
      "risk_data_available": true,
      "nodes_explored": 120,
      "computation_time_ms": 12.4,
      "path_cost": 65000.0,
      "diversity": {"shared_interior_edge_ratio": 0.0}
    }
  ],
  "route_count": 3,
  "incident_data": {"record_count": 225, "source": "bundled_csv"}
}
```

The values above illustrate the contract only. Tests will use deterministic graph fixtures, not these sample values.

### 5.2 Heatmap endpoint

`GET /api/safety-heatmap/` will return only records from the bundled dataset:

```json
{
  "points": [
    {"lat": 28.564041, "lon": 77.334413, "intensity": 0.4}
  ],
  "radius_meters": 200,
  "record_count": 225,
  "source": "bundled_csv"
}
```

No synthetic hotspot will be generated. An empty dataset produces an empty point list and a clear empty state.

### 5.3 Error contract

Invalid coordinates return 400 with a field-specific message. An unreachable graph returns 404. Upstream road-data failures return 503. Unexpected failures return a generic 500 response without exposing credentials or internal tracebacks.

## 6. Database and configuration changes

No database migration is planned for the routing, heatmap, or theme work. The existing incident CSV remains the source of truth for the available data, and road graphs are external cached resources.

Django's built-in authentication framework and SQLite configuration will remain. No custom authentication or reporting implementation currently exists, so there is no existing reporting feature to preserve or migrate. The final documentation will distinguish framework support from implemented product features.

Configuration changes:

- Add `.env.example` with Django secret, debug, allowed-host, road-data timeout, graph-cache, and risk-radius settings.
- Remove the committed secret key and read it from the environment with a development-only fallback.
- Make debug mode and allowed hosts environment-driven.
- Add request timeouts and user-agent identification for public map services.
- Add `.dockerignore` to exclude local environments, caches, Git data, and generated assets that do not belong in the image.
- Do not add or require any LLM credential.

## 7. Frontend and visual changes

### 7.1 Tailwind and reusable UI

- Add a pinned Tailwind CSS build using the official CLI and a committed lockfile.
- Move existing layout and component styles into Tailwind utilities and shared theme tokens.
- Retain only Leaflet control, route, and heatmap styling that cannot be expressed cleanly with utilities.
- Create reusable Django partials for route cards and comparison rows.
- Use one shared JavaScript route renderer instead of route-specific markup.
- Replace hard-coded route cards, route names, safety values, and travel times with API data.

### 7.2 Route comparison

- Show one card per unique route.
- Mark the safest route with a safe recommendation label only when it has the lowest risk objective among comparable routes.
- Mark the shortest route only when it is the Dijkstra result.
- Show balanced and alternative labels from the API rather than assuming a fixed count or order.
- Show distance, estimated travel time, record score, proximity risk level, and a short data-based explanation.
- Keep a compact comparison table for the shortest, safest, and balanced objectives.

### 7.3 Map

- Draw one Leaflet polyline per returned route.
- Use green, blue, purple, and orange route roles, with the selected route more prominent.
- Keep unselected routes visible at reduced opacity.
- Replace route layers on a new response and highlight only the selected route.
- Fit map bounds to the selected route when selection changes.
- Use distinct origin and destination markers.
- Never replace route geometry with a straight origin-to-destination line.

### 7.4 Heatmap

- Add a map control that defaults to off.
- Render incident points through the Leaflet heat layer with a server-provided intensity and documented radius.
- Keep routes and markers visible above the heat layer.
- Show an empty state when the API returns no supported records.

### 7.5 Themes

- Store light or dark preference in local storage and apply it before first paint to prevent a flash.
- Use a single `data-theme` attribute and shared CSS variables.
- Replace hard-coded colours in application components with theme-aware Tailwind utilities.
- Swap the Leaflet tile layer between OpenStreetMap light tiles and CARTO dark tiles.
- Keep the selected route and heatmap state when the theme changes.
- Style Leaflet controls and attribution for both themes.

## 8. Testing strategy

### 8.1 Backend unit tests

- Dijkstra returns the known minimum-distance path.
- Dijkstra handles one-way edges and disconnected graphs.
- Modified A* returns the minimum configured cost on a known graph.
- The A* heuristic does not overestimate the remaining cost.
- The safest objective selects a lower-risk longer path on a controlled graph.
- The balanced objective uses its documented weighting.
- Distance equals the sum of selected edge lengths.
- Risk and safety metrics use only selected edges.
- Alternatives are exact-distinct and pass the diversity threshold when another valid path exists.
- Insufficient alternatives produce fewer routes without fabricated duplicates.
- Invalid coordinates and unavailable upstream services return the documented status codes.

### 8.2 Integration and regression tests

- Route API returns the documented contract and consistent distance units.
- Heatmap API returns only bundled incident points.
- The application starts with no LLM credential.
- Django authentication framework and admin routes remain available.
- Static pages load without JavaScript syntax errors.
- Docker configuration can build and start the application.

### 8.3 Browser tests

Use deterministic API fixtures so browser tests do not depend on public map services. Cover:

- Every route is drawn.
- Selecting a route changes the highlighted polyline and details.
- Old polylines are removed after a new response.
- The heatmap toggles independently and coexists with routes.
- Light and dark themes change application styling and map tiles.
- Theme changes preserve route selection.
- Origin and destination markers remain visible.

### 8.4 Quality gates

Each implementation phase will run the relevant subset of:

```text
python manage.py check
python manage.py test
python -m compileall
ruff check
ruff format --check
npm run build:css
node --check
npm run test:e2e
```

Tests that require a public road-data, tile, or geocoding service will be separate optional smoke tests. Required CI tests will be deterministic and offline.

## 9. Implementation phases and commits

| Phase | Work | Commit |
|---|---|---|
| 0 | Audit and roadmap | `docs: document SAFE PATH improvement roadmap` |
| 1 | Remove DeepSeek and add deterministic local risk fallback | `chore: completely remove DeepSeek integration` |
| 2a | Add directed road graph, Dijkstra, and modified A* | `feat(daa): implement graph-based Dijkstra and modified A* routing` |
| 2b | Add diverse alternatives and structured route API | `feat(routing): generate diverse safest shortest and balanced alternatives` |
| 2c | Add routing regression coverage | `test(routing): validate path distance risk and route diversity` |
| 3 | Add reusable route cards and comparison UI | `feat(ui): add route recommendation and comparison interface` |
| 4 | Render and select multiple road routes | `feat(map): render and interact with alternative road routes` |
| 5 | Add incident heatmap layer and toggle | `feat(map): add interactive incident heatmap layer` |
| 6a | Add application theme state and styling | `feat(ui): implement application-wide dark and light themes` |
| 6b | Synchronise map tiles and overlays with theme | `feat(map): synchronize map tiles and overlays with application theme` |
| 7 | Refine responsive navigation experience | `ui: refine SAFE PATH navigation experience` |
| 8 | Add map and application regression coverage | `test: add routing map and application regression tests` |
| 9 | Update README, diagrams, and limitations | `docs: update SAFE PATH architecture and implementation documentation` |

Each commit will contain one coherent, checked change. Existing history will not be rewritten.

## 10. Risks and dependencies

| Risk or dependency | Impact | Mitigation |
|---|---|---|
| Overpass-compatible provider availability and usage limits | Slow or failed road-data download | Paid or self-hosted production provider, bounded timeout, in-process cache, bounded area, clear 503 response |
| OSM road-data parsing and topology limits | Missing roads or turn restrictions | Preserve actual one-way edges, test the parser with fixtures, and document the limitations |
| Sparse and unverified incident CSV | Weak or misleading safety claims | Label the source and coverage, never describe it as real-time, avoid claiming safety where coverage is absent |
| OSM graph incompleteness and turn restrictions | Route may differ from a production router | Document the limitation and do not claim full turn-restriction support |
| Public tile and geocoding policies | Throttling or blocked requests | Attribution, conservative client usage, server-side geocoding proxy with timeout and user agent |
| No existing user-report or custom authentication feature | Requested regression coverage cannot test absent features | Preserve Django framework support and state the product limitation accurately |
| Tailwind and browser-test tooling | Additional Node build step | Use pinned packages, commit lockfiles, and document one build command |
| Different runtime versions | Current pinned NumPy and pandas versions do not install on the audit host's Python 3.15 | Standardise development and CI on Python 3.13, matching the Docker image |
| Limited incident history | Record score has limited validity | Keep the formula transparent, expose source and coverage, and support future incident sources without changing route logic |

## 11. Explicitly deferred work

- Deep learning, FDL, neural safety models, and model training.
- Replacement LLM providers and LLM-generated risk explanations.
- A full React application migration.
- A new user-reporting product or authentication workflow, because neither currently exists.
- PostgreSQL, PostGIS, FastAPI microservices, and police API integrations, because none are part of the current working implementation.
- Additional graph algorithms beyond Dijkstra and modified A*.

## 12. Acceptance mapping

| Acceptance requirement | Planned evidence |
|---|---|
| DeepSeek fully removed | Repository search, start test, and removal commit |
| Genuine shortest route | Dijkstra unit test and shortest-role assertion |
| Safety-aware route | Modified A* cost tests and controlled risk-priority test |
| Distinct alternatives | Edge-sequence duplicate test and interior-overlap test |
| Accurate distance | Selected-edge sum test and API-to-card consistency test |
| All routes visible | Browser polyline-count test |
| Correct route selection | Browser layer-state test |
| Independent heatmap | Browser toggle and coexistence test |
| Bundled-data incident heatmap | Heatmap API fixture and source check |
| Complete light and dark themes | Theme state and browser screenshot or computed-style checks |
| Theme-aware map | Tile-source test and browser theme test |
| Authentication and reporting regression | Django auth smoke test and explicit limitation for absent reporting feature |
| Reusable UI and Tailwind | Shared partials, shared renderer, and Tailwind build check |
| Minimal comments and no em dashes | Review checklist and repository character search |
| Passing tests | Local and CI command results |
| Meaningful Git history | Phase commits with scoped changes |
