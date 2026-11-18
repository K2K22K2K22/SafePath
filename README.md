# SAFE PATH

SAFE PATH is a Django navigation application that compares routes over a real directed road graph. It combines shortest-path search, safety-weighted path search, and deterministic incident-proximity scoring so users can inspect distance, estimated travel time, incident-record proximity risk, and route differences.

The application does not use an LLM, deep learning, FDL, or an external AI provider. Route geometry, distances, risk values, and route labels are computed from source data.

## Highlights

- Real OpenStreetMap road graph from a bounded Overpass-compatible read-only source, with directed edges, one-way rules, access restrictions, node barriers, and consecutive-node edge segments
- Custom Dijkstra and modified A* implementations with bounded searches and admissible distance heuristics
- Up to four unique routes, including shortest, safest when data coverage supports it, balanced, and genuinely distinct alternatives
- Deterministic risk scoring from bundled incident records, with unknown safety when a route is not fully covered
- Route cards, side-by-side comparison, distinct map colors, and route selection
- Optional Leaflet heatmap generated from the same validated incident records used by route scoring
- Persisted light and dark application themes with matching map tile layers
- Responsive Django templates and Tailwind CSS with no frontend framework rewrite
- Django and REST Framework APIs with scoped throttles, external service validation, and request limits
- Ruff, Mypy, ESLint, Django, Playwright, Tailwind, and Docker CI gates

## Architecture

| Layer | Technology and responsibility |
| --- | --- |
| Web application | Django 5.2 templates and native JavaScript |
| HTTP API | Django REST Framework |
| Road graph | Bounded Overpass-compatible OSM XML parsed into an in-memory directed graph |
| Geocoding | Normalized server-side Nominatim proxy with bounded file cache and shared request pacing |
| Routing | Custom Dijkstra, modified A*, and penalty-based alternative generation |
| Risk model | Bundled CSV incidents scored against stored road-edge segments |
| Map | Leaflet 1.9.4 and Leaflet.heat 0.2.0, both vendored locally |
| Styling | Tailwind CSS 4.1.18 with committed generated CSS |
| Django storage | PostgreSQL via `DATABASE_URL`, with SQLite as the local fallback |
| CI | GitHub Actions on Python 3.13 and Node.js 22 |

SQLite does not store route or incident results. Routing uses the OSM graph and bundled CSV directly. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system, route-flow, risk-flow, frontend-state, and deployment diagrams, and [docs/DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md) for external provider policy.

## Requirements

- Python 3.13
- Node.js 22
- npm
- Internet access for an Overpass-compatible road provider, Nominatim geocoding, and map tiles
- Docker with Compose only if using the container workflow

Python 3.13 is the supported runtime used by the Docker image and CI. Some pinned binary wheels do not support Python 3.15.

## Local setup

Run these commands from a checkout containing the current implementation:

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

For local development, keep `DJANGO_DEBUG=True`. The public Overpass endpoint in `.env.example` is a low-volume development fallback with no availability guarantee. Without a CARTO key, local dark mode uses filtered OpenStreetMap tiles instead of requesting a watermarked CARTO tile. When debug mode is disabled, `DJANGO_SECRET_KEY` must contain at least 50 sufficiently random characters, `DJANGO_ALLOWED_HOSTS` must list exact production host names, and `SAFEPATH_CARTO_API_KEY` must contain a customer-owned publishable key. Startup fails when any of these requirements is missing, and obvious CARTO placeholders are rejected. Production route requests also require a paid or self-hosted Overpass-compatible provider whose exact host appears in `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS`.

Install frontend tooling and build the committed stylesheet:

```bash
npm ci
npm run build:css
```

Apply standard Django migrations and run the server:

```bash
DJANGO_DEBUG=True venv/bin/python manage.py migrate
DJANGO_DEBUG=True venv/bin/python manage.py runserver
```

Open <http://127.0.0.1:8000>.

Route requests do not require database rows. Standard Django migrations create the framework tables used by sessions and admin. Django's built-in admin remains available at `/admin/`, but SAFE PATH does not provide product accounts, user profiles, or user incident reporting.

## Docker

Set a real secret, customer-owned CARTO key, and approved road provider in `.env`, then run:

```bash
cp .env.example .env
# Replace DJANGO_SECRET_KEY and SAFEPATH_CARTO_API_KEY in .env.
# Approve the paid or self-hosted road provider host in .env.
docker compose up --build
```

The container exposes `PORT` (default `8000`) on loopback, runs Gunicorn as an unprivileged user, can apply standard Django migrations at startup, and defines a health check against `/health/`. Compose runs production security settings, so browser traffic requires a local TLS-terminating proxy, the dark basemap requires a domain-restricted CARTO key, and route requests require a paid or self-hosted road-data provider explicitly approved in `.env`. Use the debug development server for ordinary local UI work. Compose loads `.env`, including `SAFEPATH_*` values, into the container. A one-shot initializer repairs SQLite volume ownership before the application starts, so upgrades from the earlier root-owned image remain usable. When `DATABASE_URL` is unset, SQLite data and the geocoder cache stay in the `safepath_data` named volume, so container startup does not create a database in the host checkout. The image contains the application source and must be rebuilt after a source change. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for migration modes and container operation.

## Render deployment

`render.yaml` configures one native Python web service in Render's Singapore region for the academic demo. It uses Python 3.13.18, one Gunicorn worker, `/health/` health checks, generated Django secret storage, and startup migrations because Render Free services cannot run a pre-deploy command.

Before applying the Blueprint, create an external PostgreSQL database such as Neon, obtain an approved paid or self-hosted Overpass-compatible road provider, and obtain a customer-owned CARTO publishable key. Enter the exact Render hostname, HTTPS CSRF origin, PostgreSQL URL, CARTO key, and road-provider values when Render prompts. Do not commit any of them.

Render Free services use an ephemeral filesystem, support one instance, may spin down after 15 minutes of inactivity, and are not production-ready. Public Nominatim has no availability guarantee. Keep the demo at one instance unless geocoder pacing is moved to shared coordination. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#render-native-deployment) for Neon setup, exact Blueprint steps, validation, and troubleshooting.

## Configuration

All supported settings are documented in [.env.example](.env.example). Important controls include:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_DEBUG` | `False` | Enables development behavior and ephemeral local secret generation |
| `DJANGO_SECRET_KEY` | unset | Required when debug mode is off; use at least 50 sufficiently random characters |
| `DJANGO_ALLOWED_HOSTS` | local hosts in debug mode | Exact comma-separated production host names; wildcards are rejected |
| `CSRF_TRUSTED_ORIGINS` | unset | Optional comma-separated exact HTTPS origins for cross-origin requests; `DJANGO_CSRF_TRUSTED_ORIGINS` remains a legacy alias |
| `DJANGO_TRUST_X_FORWARDED_PROTO` | `False` | Trust the proxy protocol header only when a trusted proxy replaces client headers |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | HSTS lifetime in seconds; keep disabled until the deployed hostname and HTTPS redirect path are verified |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` | Include subdomains in HSTS after verifying every subdomain supports HTTPS |
| `DJANGO_SECURE_HSTS_PRELOAD` | `False` | Submit the domain to browser preload lists only after explicit review |
| `DATABASE_URL` | unset | PostgreSQL connection URL with production TLS; unset uses local SQLite |
| `SAFEPATH_DATABASE_CONN_MAX_AGE` | `60` | PostgreSQL connection lifetime in seconds |
| `PORT` | `8000` | Container port used by Gunicorn |
| `GUNICORN_WORKERS` | `2` | Gunicorn worker count |
| `GUNICORN_TIMEOUT` | `60` | Gunicorn request timeout in seconds |
| `GUNICORN_GRACEFUL_TIMEOUT` | `30` | Gunicorn graceful shutdown timeout in seconds |
| `DOCKER_STOP_GRACE_PERIOD` | `40s` | Docker shutdown grace in integer seconds with an `s` suffix only; must exceed Gunicorn's graceful timeout |
| `SAFEPATH_DATABASE_PATH` | Repository `db.sqlite3` | Optional SQLite path; Compose stores it in the `safepath_data` volume |
| `SAFEPATH_RUN_MIGRATIONS` | `false` in the image | Run migrations before Gunicorn when set to `true` |
| `SAFEPATH_CACHE_DIR` | `/tmp/safepath-cache` | Private geocoder cache and request-lock directory; must be owned by the application user with mode `0700`; Compose uses `/data/cache` |
| `SAFEPATH_CARTO_API_KEY` | unset | Required production CARTO publishable key; domain-restrict it and keep visible browser attribution |
| `SAFEPATH_GEOCODER_URL` | Nominatim search URL | Server-side geocoding proxy target |
| `SAFEPATH_GEOCODER_ALLOWED_HOSTS` | `nominatim.openstreetmap.org` | HTTPS hosts allowed for geocoding |
| `SAFEPATH_GEOCODER_CACHE_MAX_ENTRIES` | `1000` | Maximum cached geocoder results |
| `SAFEPATH_GEOCODER_CACHE_TTL_SECONDS` | `86400` | Geocoder cache lifetime in seconds |
| `SAFEPATH_ROUTE_THROTTLE_RATE` | `20/minute` | Route API request limit |
| `SAFEPATH_GEOCODE_THROTTLE_RATE` | `30/minute` | Geocoding API request limit |
| `SAFEPATH_HEATMAP_THROTTLE_RATE` | `60/minute` | Heatmap API request limit |
| `SAFEPATH_MAX_ROUTE_SPAN_METERS` | `50000` | Maximum origin-to-destination span |
| `SAFEPATH_MAX_ROUTE_AREA` | `1.0` | Maximum requested route area |
| `SAFEPATH_MAX_SNAP_DISTANCE_METERS` | `1000` | Maximum endpoint snap distance |
| `SAFEPATH_MAX_NODES_EXPLORED` | `100000` | Per-search exploration limit |
| `SAFEPATH_GRAPH_CACHE_MAX_ENTRIES` | `8` | Maximum cached OSM graphs |
| `SAFEPATH_GRAPH_CACHE_TTL_SECONDS` | `86400` | OSM graph cache lifetime |
| `SAFEPATH_OSM_API_URL` | `https://overpass-api.de/api/interpreter` | Overpass-compatible road provider; public endpoint is development-only |
| `SAFEPATH_OSM_API_ALLOWED_HOSTS` | `overpass-api.de` | Exact HTTPS hosts allowed for road data |
| `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS` | unset | Exact paid or self-hosted provider hosts explicitly approved for production |
| `SAFEPATH_OSM_API_MAX_BYTES` | `25000000` | Maximum total downloaded OSM bytes per load |
| `SAFEPATH_OSM_API_MAX_REQUESTS` | `16` | Maximum OSM requests per load |
| `SAFEPATH_OSM_API_MAX_SPLIT_DEPTH` | `3` | Maximum bounding-box split depth |
| `SAFEPATH_ROAD_DATA_TIMEOUT_SECONDS` | `30` | Road-data acquisition deadline checked between response reads |

## HTTP API

All API endpoints accept `GET` requests. Browser code calls relative, same-origin URLs, but the server does not enforce HTTP `Origin` headers.

### Route options

```text
GET /api/routes/?start_lat=28.4748&start_lon=77.4764&end_lat=28.48&end_lon=77.482
```

A successful response contains:

- `routes`: up to four route objects with geometry, labels, algorithm, distance, duration, proximity risk, record score, coverage, search metrics, and diversity metrics
- `route_count`: number of routes actually generated
- `origin` and `destination`: validated request coordinates
- `incident_data`: bundled-source provenance, unknown metadata, and coverage semantics
- `original_route`: geometry of the shortest route
- `safe_path`: geometry of the supported safest route, or `null` when no route qualifies
- `safest_route_available`: whether a supported `safest` route exists
- `distance_meters`, `avg_risk`, `nodes`, and `segments`: compatibility summary fields for the shortest route

Each route also includes `type` and `duration_source`.

Route labels are emitted only for supported model roles:

- `shortest`: minimum road-edge distance in the loaded graph
- `safest`: lowest modeled risk among the generated, eligible routes with every edge fully covered by a record-proximity zone; the interface renders this as `Lowest modeled risk`
- `balanced`: modified A* result with `beta=2.0`
- `alternative`: distinct candidate generated with temporary edge penalties

A single route can carry multiple labels when it wins more than one objective. The application does not fabricate a missing `safest` label when incident coverage is insufficient, and `safe_path` remains `null` in that case. Exceeding the configured search exploration limit returns HTTP 503.

`/api/safe-route/` remains an alias of `/api/routes/` for compatibility.

### Geocoding proxy

```text
GET /api/geocode/?q=Connaught%20Place%20Delhi
```

The proxy validates the query length, restricts the provider to configured HTTPS hosts, rejects redirects, applies a timeout, and returns only finite, valid coordinates. It uses an identifying User-Agent, visible provider attribution, and browser autocomplete suppression. Normalized successful results are cached in a bounded file cache. A shared file lock limits uncached provider requests to one per second across workers in one instance; multiple instances need external coordination.

### Incident heatmap

```text
GET /api/safety-heatmap/
```

The response contains validated incident points, their normalized intensity, the 200 metre influence radius, record count, source provenance, unknown source metadata, and coverage semantics. The map layer is off by default and is independent from route layers.

### Health and errors

```text
GET /health/
GET /health/live/
GET /health/ready/
```

`/health/` and `/health/live/` are lightweight liveness checks. They return `{"status": "ok"}` when Django can serve requests and do not call the database or external providers. `/health/ready/` performs only a database `SELECT 1` check and returns HTTP 503 with `{"status": "not_ready", "code": "database_unavailable"}` when the database cannot be reached.

API failures return a safe `detail` message and a stable `code`. Expected failures include `invalid_request`, `route_not_found`, `road_provider_unavailable`, `geocoder_unavailable`, `invalid_provider_response`, `search_limit_exceeded`, and `rate_limit_exceeded`. Unexpected failures return only `{"detail": "An unexpected error occurred.", "code": "internal_error"}`. Raw exception text and tracebacks are never returned.

## Routing model

### Directed road graph

Overpass-compatible OSM ways are split into edges between consecutive nodes. The parser:

- Keeps only drivable highway classes
- Applies access hierarchy and removes restricted or blocked access
- Honors one-way direction rules
- Removes edges blocked by physical node barriers
- Stores source and target coordinates for each edge
- Calculates edge distance from consecutive OSM node coordinates
- Estimates travel time from road class and `maxspeed` when available

Every edge distance must be at least 99% of the endpoint geodesic distance. The same 99% lower bound is used by the A* heuristic, keeping the heuristic admissible.

### Search objectives

The edge cost is:

```text
cost = distance_meters + beta * risk * distance_meters
```

- Dijkstra with `beta=0` finds the shortest route.
- Modified A* with `beta=8.0` produces the safety-weighted candidate.
- Modified A* with `beta=2.0` produces the balanced candidate.

The connected multi-source Dijkstra result is reused as the shortest route. The candidate pool also applies temporary penalties to edges used by base paths, running each distinct penalty set once. Exact paths are deduplicated. Interior-edge overlap is measured after trimming common start and end edges, and an alternative is retained only when its overlap ratio is at most `0.75` relative to selected routes.

The response can contain fewer than four routes when the loaded graph does not support that many connected, distinct paths. It never repeats a path or invents route geometry.

### Incident risk

Risk scoring is deterministic and uses no predictive model:

1. Read the bundled CSV and remove exact duplicate rows.
2. Reject rows with missing, non-finite, out-of-range, or invalid severity values.
3. Normalize severity from 1 to 5 into a value from 0 to 1.
4. Measure distance from each incident to the stored segment between each edge's endpoints.
5. Apply a 200 metre radius with linear proximity decay.
6. Aggregate severity-weighted exposure.
7. Convert edge exposure with `edge_risk = 1 - exp(-exposure)`.

For a fully covered route, proximity risk is the distance-weighted mean of its edge risks:

```text
route_risk = sum(distance_m * edge_risk) / sum(distance_m)
safety_score = round((1 - route_risk) * 100)
```

The API retains `risk_score` and `safety_score` field names for compatibility. The interface presents them as proximity risk and record score. Risk levels are `low` below `0.2`, `moderate` below `0.5`, and `high` otherwise.

Incident coverage is tracked separately from risk magnitude. For each edge, the application unions the portions inside the 200 metre influence zones of accepted records and stores the actual covered length in metres. A route is fully covered only when every edge is fully covered. Any partial or uncovered route receives unknown safety and no `safest` label. Partial coverage is never treated as zero risk, and `safe_path` is `null` when no supported safest route exists.

The bundled file contains 225 raw rows and 193 valid unique incident records. It is unverified demonstration data. Its original source, collection methodology, collection date, geographical coverage, license, and redistribution permission are unknown. See [`data/README.md`](data/README.md) and [`data/source_metadata.json`](data/source_metadata.json).

## Frontend behavior

- The route planner supports address search, browser location, map-point selection, swapping, and clearing.
- Every returned route remains visible on the map with its own color.
- Selecting a route card highlights that line and updates its map emphasis.
- Route cards and comparison rows show only API values.
- Loading, empty, error, and unknown-coverage states are explicit.
- The heatmap uses unverified demonstration incident points and starts disabled.
- Route cards show actual record-proximity coverage and explain when a safety estimate is unavailable.
- Theme changes persist in local storage and replace only the tile layer. Route selection and heatmap state remain intact.
- Light tiles use the canonical OpenStreetMap raster endpoint. Dark tiles use CARTO raster tiles when a customer-owned publishable key is configured; local development without a key uses filtered OpenStreetMap tiles. OpenStreetMap, Nominatim, and CARTO attribution remain visible.
- The layout is usable down to 320 CSS pixels without horizontal page overflow.

## Testing and quality gates

Run Python checks:

```bash
DJANGO_DEBUG=True venv/bin/python manage.py check
DJANGO_DEBUG=True venv/bin/python manage.py test
venv/bin/ruff check .
venv/bin/ruff format --check .
venv/bin/mypy Model web safepath_backend scripts manage.py
DJANGO_DEBUG=True venv/bin/python -m compileall -q Model web safepath_backend manage.py
```

Run frontend and browser checks:

```bash
npm ci
npm run build:css
npm run lint:js
npm run check:js
npx playwright install chromium
npm run test:e2e
```

The Playwright suite uses deterministic mocked geocode, route, heatmap, and tile responses. It covers desktop and mobile Chromium, route rendering and selection, heatmap isolation and empty state, theme switching, API errors, console errors, and overflow.

Current local result:

- 190 Django tests passed
- 14 Playwright tests passed across desktop and mobile Chromium
- Ruff lint and format checks passed
- Mypy passed
- ESLint and Node syntax checks passed
- Tailwind build and Django system checks passed
- npm production dependency audit (`npm audit --omit=dev`) reported zero vulnerabilities

The full npm development-tool audit currently reports two high-severity findings in Tailwind's transitive `@parcel/watcher` and `picomatch` packages. They affect local build tooling only. `npm audit --omit=dev` reports zero vulnerabilities, and no patched upstream `picomatch` release is currently available.

GitHub Actions runs the same Python, frontend, and browser gates, then builds the Docker image, waits for its own health check, and verifies local static assets. A fresh Podman image build and runtime passed locally. The native Docker daemon was unavailable in the delivery environment, so native Docker and remote CI remain required evidence.

## Project map

```text
Model/
  views.py                    REST API endpoints
  utils/osm_graph.py          Bounded Overpass ingestion, limits, directed graph conversion
  utils/risk_scoring.py       Incident validation, proximity exposure, coverage
  utils/routing.py            Dijkstra and modified A* search core
  utils/errors.py             Typed API errors and safe exception handling
  utils/route_service.py      Route roles, alternatives, labels, metrics
  utils/road_graph.py         Validated graph and edge structures
web/
  templates/web/              Django UI and reusable partials
  static/web/js/script.js     API, map, route, heatmap, and theme state
  static/web/css/             Tailwind source and generated CSS
  static/web/vendor/          Pinned Leaflet assets and licenses
  e2e/                        Playwright regression tests
  test_*.py                   Django API, routing, risk, and smoke tests
docs/
  IMPROVEMENT_ROADMAP.md      Original audit and phased plan
  ARCHITECTURE.md             Architecture and flow diagrams
  DATA_PROVIDERS.md           External provider policy and limits
```

## Delivery phases

| Phase | Result | Commit |
| --- | --- | --- |
| 0 | Repository audit and implementation roadmap | `15e670b` |
| 1 | DeepSeek removal and deterministic risk coverage | `2ae3bb3`, `bec727d` |
| 2 | Django hardening, directed OSM graph, Dijkstra, modified A*, safeguards, and routing tests | `a268e33` through `e8af93e` |
| 3 | Tailwind interface, API-driven route cards, comparison, geocoding proxy, and local favicon | `a6e779d` |
| 4 | Multi-route map rendering, colors, legend, and selection | `88f59c3` |
| 5 | Bundled-data independent incident heatmap | `8336f8d` |
| 6 | Persisted application theme and synchronized map tiles | `429b86a`, `dd1895c` |
| 7 | Responsive navigation refinement through 320 px | `ca7b361` |
| 8 | Browser tests, static analysis, local assets, health check, CI, and container hardening | `e7fe8d6`, `56b8b07`, `5ec7aef`, `965ffc3` |
| 9 | Initial setup, API, algorithm, architecture, testing, and limitation documentation | `484ddba` |
| 10 | Pairwise route diversity, search-limit API, container runtime, and final documentation corrections | `55259aa`, `ced06b8`, `4977d13`, `ab83c59`, `2780c70` |
| 11 | Review-driven container ownership, risk-language, and CI diagnostics fixes | `541f94e` |

## Limitations and deliberate omissions

- Incident data is a static bundled dataset, not a live police or emergency feed.
- The CSV is explicitly unverified demonstration data. Source, collection methodology, collection date, geographical coverage, license, and redistribution permission remain unknown.
- Record scores and proximity risk describe distance to bundled records, not personal safety, crime likelihood, or an individual risk assessment. The interface states this beside the route planner.
- Travel time is an estimate from road class and available speed data, not live traffic.
- OSM road snapshots and Nominatim results depend on external service availability and freshness.
- Map tiles remain network-dependent even though map libraries are vendored locally.
- Record-proximity coverage does not establish real-world incident completeness. Routes that are not fully covered are reported as unrated rather than safe.
- OSM turn restrictions and relation-based restrictions are not applied, so routes may ignore valid turn bans and differ from production routers.
- The included Docker configuration runs Gunicorn as a non-root user, but public deployment still requires an external production database and production provider configuration.
- SAFE PATH has no custom authentication workflow, user accounts, personalization, live incident reporting, or incident moderation.
- No external LLM, deep learning model, FDL component, or fabricated fallback data is present.

## License

SAFE PATH is licensed under GPL v3. See [LICENSE](LICENSE). Vendored Leaflet dependencies retain their own licenses under `web/static/web/vendor/`.
