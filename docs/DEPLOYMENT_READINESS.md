# Deployment Readiness

This document records the deployment-hardening workstream separately from the project's earlier development phases listed in the README.

## Baseline

Audit date: 2026-11-18

- Branch: `main`
- Commit: `9085090d571d965c15577894ac7aee28e9f3283d`
- Working tree: clean at the start of the audit
- Supported runtime: Python 3.13
- Audit runtime: CPython 3.13.18 in an isolated virtual environment
- Node.js runtime: 22.23.1
- Docker CLI: 29.10.0
- Docker Compose: 5.7.1
- Local Docker daemon: unavailable, so container runtime verification must run in CI

## Baseline checks

The following checks ran successfully against commit `9085090`:

| Check | Command | Result |
| --- | --- | --- |
| Django system check | `DJANGO_DEBUG=True python manage.py check` | Passed, no issues |
| Django tests | `DJANGO_DEBUG=True python manage.py test --verbosity 2` | Passed, 61 tests |
| Python compilation | `python -m compileall -q Model web safepath_backend manage.py` | Passed |
| Ruff lint | `ruff check .` | Passed |
| Ruff format | `ruff format --check .` | Passed, 36 files |
| Mypy | `mypy Model web safepath_backend manage.py` | Passed, 30 source files |
| Node dependencies | `npm ci` | Installed, 2 high-severity development dependency findings |
| Tailwind build | `npm run build:css` | Passed, generated CSS unchanged |
| ESLint | `npm run lint:js` | Passed |
| JavaScript syntax | `npm run check:js` | Passed |
| Playwright | `npm run test:e2e` | Passed, 12 tests on desktop and mobile Chromium |

A production settings check with a deliberately short test key reported five warnings:

- `SECURE_HSTS_SECONDS` is not configured.
- `SECURE_SSL_REDIRECT` is not enabled.
- The test secret key is not long or random enough for production.
- `SESSION_COOKIE_SECURE` is not enabled.
- `CSRF_COOKIE_SECURE` is not enabled.

The latest remote CI run for `9085090` passed Python, frontend, browser, and Compose configuration checks. It failed the new Compose startup assertion that checks for a host checkout database file. Earlier CI run `44215010163` passed for commit `80fbfaf`. The Compose startup failure must be resolved before deployment readiness can be claimed.

## Phase 1 runtime lifecycle

Commits `d4c06e6`, `ca7f9ee`, and `eac9d12` replaced the development server with Gunicorn, added a non-root image, constrained migration mode, repaired legacy SQLite volume ownership, sent container logs to one stream, and enforced a Docker stop grace greater than the Gunicorn graceful timeout. Local Compose configuration, entrypoint, Gunicorn, and test checks pass. The Docker daemon was unavailable locally, so the first remote CI run of the strengthened container lifecycle remains the required runtime evidence.

## Phase 2 static assets

Commits `0c5dad8` and `74f6bbf` configured WhiteNoise with compressed manifest storage and added live verification for rendered URLs, CSS references, content types, redirects, and gzip payloads. Production static collection passes locally.

## Phase 3 PostgreSQL

Commit `c1638f5` added `DATABASE_URL` support through `dj-database-url`, PostgreSQL SSL query options, persistent connection health checks, SQLite fallback, and PostgreSQL CI migrations and tests. The security phase also requires encrypted production PostgreSQL connections, keeps the raw connection URL out of Django's uppercase settings, and verifies a database-backed session round trip. PostgreSQL 16.16 passed migrations, `migrate --check`, and the Django suite locally through Podman.

## Phase 4 security

Production settings now require a strong secret and exact host names, redirect HTTP to HTTPS, mark session and CSRF cookies secure, validate trusted CSRF origins, and keep HSTS disabled by default. Forwarded-protocol trust is disabled unless explicitly enabled behind a controlled proxy, and Compose binds the application to loopback. Health and static-asset probes use an explicit host header so they work without weakening the production host allowlist. The production check gate permits only the documented, deferred HSTS warnings and fails on every other deployment warning or error. The final local matrix passed 92 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 12 browser tests. Podman rebuilt the image and verified static collection, migrations, non-root Gunicorn, trusted and untrusted forwarded-protocol behavior, the health probe, volume ownership repair, and every manifest, CSS reference, and gzip response. Native Docker and remote CI remain required for final runtime evidence.

## Phase 5 external service compliance

### Road data provider

The road loader now sends fixed, bounded Overpass QL for drivable road classes to an explicitly configured HTTPS host instead of calling the OpenStreetMap editing or Map API. Public Overpass remains a low-volume development fallback only. Production route requests require an exact host in `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS`, and the production check script enforces the same rule. Known public providers remain rejected even when listed. Canonical host comparison, UTF-8-only XML, explicit oversized-error splitting, and the existing area, request, byte, deadline, split, XML, and graph limits remain active. Provider requests are serialized within one process.

The selected provider is Overpass.ch at `https://api.overpass.ch/v1/interpreter`. Requests use a form-encoded `data` POST with XML output and authenticate with `SAFEPATH_OSM_API_KEY` in the `X-API-Key` header. The key is never placed in the URL, query string, logs, exception text, or HTTP responses. The production gate rejects a missing key for that host, Render stores the key as a secret, and the application-wide limiter caps interpreter requests at 60 per rolling minute including bbox splits. The supported one-worker configuration sends one request at a time, within the selected plan's two-query concurrency limit, and the graph cache avoids repeated downloads. `docs/DATA_PROVIDERS.md` records configuration, limits, caching, licensing, attribution, failure behavior, and the multi-instance constraint. The Phase 5 local matrix passed 111 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 12 browser tests. A fresh Podman image build and runtime verified the provider configuration, migrations, health probe, and graceful stop. Live requests to two public Overpass instances timed out from this environment, so public provider response availability remains unverified.

### Geocoding and map tiles

The geocoder now uses an identifying User-Agent, visible Nominatim and OpenStreetMap attribution, browser autocomplete suppression, normalized queries, successful-result caching, and a shared file lock that limits uncached provider request starts to one per second across Gunicorn workers sharing one instance filesystem. Provider responses are capped at 64 KiB. Malformed, oversized, and invalid-only payloads are rejected and not cached. The cache directory must be an application-owned real directory with mode `0700`; public and symlinked directories fail startup because the file cache deserializes local files. Cache failures do not block valid searches, while request-lock failures and invalid lock state return HTTP 503 because pacing cannot be guaranteed. The default DRF cache remains process-local for throttling; geocoder results use a separate bounded file cache.

The browser uses the canonical OpenStreetMap standard raster endpoint for the light theme and CARTO's current raster basemap endpoint for the dark theme when a customer-owned, domain-restricted CARTO publishable key is configured. Production rejects obvious placeholder keys. Local development without a key uses filtered OpenStreetMap tiles instead of requesting a watermarked CARTO tile. The key remains visible in browser requests and is never proxied through the application. The geocoding local matrix passed 137 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 12 browser tests. Compose configuration and a fresh Podman image runtime also passed. Public Nominatim has no availability guarantee, and separate application instances do not share the local pacing lock.

## Phase 6 incident provenance and coverage

Repository history describes `data/delhi_crime_data.csv` as fictitious data for testing and demonstration. `data/source_metadata.json` now records that evidence and leaves the original source, collection methodology, collection date, geographical coverage, license, and redistribution permission explicitly unknown. The API, interface, and documentation label the records as unverified demonstration data.

Coverage no longer uses an incident-coordinate bounding rectangle. The scorer unions each edge's intersections with 200 metre record-proximity zones, stores actual covered length, and requires every route edge to be fully covered before reporting a safety estimate or assigning `safest`. Partial and uncovered routes remain unrated, and the API returns `safe_path=null` when no supported safest route exists. The Phase 6 local matrix passed 155 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 14 browser tests. A fresh Podman image build passed.

## Phase 7 routing correctness and performance

The routing audit confirmed that Dijkstra minimizes actual road-edge distance, modified A* returns the minimum configured objective cost, its 99% geodesic heuristic remains admissible, valid edge costs remain non-negative, path distances sum actual edge lengths, risk is length-weighted, partial coverage remains unknown, `safest` is limited to fully covered generated candidates, `shortest` uses graph distance, `balanced` uses `beta=2.0`, alternatives satisfy the distinctness threshold, disconnected graphs return no path, endpoint snapping respects its distance limit, search limits produce controlled errors, and upstream failures do not crash the API. The UI explanation remains `Lowest modeled risk among the generated, eligible routes.`

Two redundant search costs were removed without changing either search algorithm or the alternative strategy. The connected multi-source Dijkstra result is reused as the shortest route, and base paths with the same edge set run one penalty-search group. Existing request, graph, response-byte, and node-exploration safeguards remain unchanged.

A deterministic synthetic benchmark used OSM-shaped short and medium grids. The short graph had 100 nodes and 360 edges; the medium graph had 900 nodes and 3,480 edges. The provider request was mocked, so these figures do not claim live provider latency.

| Measurement | Short | Medium |
| --- | ---: | ---: |
| Mocked provider download, parse, and graph build | 3.9 ms | 40.1 ms |
| Graph construction | 3.2 ms | 34.3 ms |
| Synthetic proximity scoring | 139.9 ms | 1,426.5 ms |
| Dijkstra | 0.18 ms | 1.85 ms |
| Modified A* | 0.25 ms | 2.99 ms |
| Cold API response | 65.5 ms | 484.1 ms |
| Warm cached-risk API response | 2.4 ms | 18.1 ms |

Against commit `7ac17ff` in the same harness, route-option generation fell from 3.0 ms to 2.3 ms for the short graph and from 32.1 ms to 24.0 ms for the medium graph. Warm API responses fell from 4.2 ms to 2.4 ms and from 38.4 ms to 18.1 ms respectively. Cold API responses fell from 74.0 ms to 65.5 ms and from 571.9 ms to 484.1 ms. These are local synthetic measurements, not service-level objectives. One bounded public Overpass development request failed with `RoadDataUnavailable` in 603 ms, so live provider timing remains unverified.

The Phase 7 local matrix passed 164 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 14 browser tests. A fresh Podman image build and runtime passed.

## Phase 8 health, logging, and errors

`/health/` and `/health/live/` remain lightweight liveness checks and do not access the database or external providers. `/health/ready/` performs only a database `SELECT 1` check, returns HTTP 503 when the database is unavailable, and does not expose connection details. Django's production error pages now include safe 404 and 500 templates.

Expected API failures use typed errors with stable response codes. The covered cases are invalid coordinates, unsupported route distance, no connected path, road-provider unavailability, geocoder unavailability, rate limiting, search exploration limits, and invalid provider responses. Unexpected failures return a generic `internal_error` response without exception text or tracebacks.

Django application logs use standard output and standard error. Gunicorn access logs use the URL path without its query string. Application error logs use the resolved route pattern, error code, and exception type. The shared formatter removes URL query strings, URL credentials, and sensitive assignments, and redacts exception messages. Expected client validation failures are not logged as application errors.

A follow-up security review bounded PostgreSQL connection establishment at five seconds and statements at ten seconds, routed third-party and Gunicorn errors through the safe formatter, and confirmed that unexpected route errors return a generic response instead of internal exception text.

The Phase 8 local matrix passed 182 Django tests on SQLite and PostgreSQL, Python lint, format, type, compile, and dependency checks, frontend build, lint, syntax, and 14 browser tests. A fresh Podman image build and runtime verified liveness, readiness, the 404 page, query-free access logs, migrations, and graceful stop. Native Docker and remote CI evidence remains pending because no push was performed.

## Phase 9 Render deployment configuration

The repository now contains `.python-version`, a native Python `render.yaml`, a current-schema validator, a checked-in Render schema snapshot retrieved on 2026-11-19, and deterministic Blueprint tests. The Blueprint configures one Free web service in Singapore with one Gunicorn worker, a 40 second shutdown allowance, `/health/` health checks, a generated Django secret, and no secret values in the repository. Its startup command runs the production configuration gate before migrations and Gunicorn. It uses startup migrations because Render Free services cannot run a pre-deploy command, and it intentionally does not create Render Free PostgreSQL because that database expires after 30 days. Required CI validates against the checked-in snapshot, while a weekly and manually dispatched job validates against Render's live schema so provider availability does not block unrelated pull requests.

`CSRF_TRUSTED_ORIGINS` is now the documented environment variable. `DJANGO_CSRF_TRUSTED_ORIGINS` remains accepted as a legacy alias. The deployment guide covers exact Neon, CARTO, road-provider, host, and origin values, Blueprint creation, migration behavior, Free-plan constraints, validation, and troubleshooting. No Render or Neon resource was created and no public deployment was attempted.

The Phase 9 local matrix passed 188 Django tests, Python lint, format, type, and compile checks. The Blueprint passed `https://render.com/schema/render.yaml.json` validation on 2026-11-18. Remote CI and a real Render deploy remain pending because no push or public deployment was performed.

## Phase 10 dependency and deployment verification

The first production Python audit found 88 known vulnerabilities across eight outdated pins. Django was upgraded from 5.2.8 to 5.2.17, Django REST Framework from 3.16.1 to 3.18.2, and the affected `certifi`, `idna`, `python-dotenv`, `requests`, `sqlparse`, and `urllib3` pins were upgraded to their fixed releases. `pip-audit -r requirements.txt` then reported no known vulnerabilities. The updated dependencies passed all 190 Django tests on SQLite and PostgreSQL 16, plus Django checks, Ruff, Mypy, compilation, and the Render Blueprint validation.

`npm audit --omit=dev` reports zero vulnerabilities. An earlier full frontend audit reported two high-severity development-tool findings through Tailwind's transitive `@parcel/watcher` and `picomatch` packages. The `picomatch` advisory, `GHSA-fc5q-39xc-vjpf`, was withdrawn on 2026-11-18 after the upstream maintainer determined that the reported regular-expression denial of service requires attacker-controlled glob patterns. No patched upstream `picomatch` release was available during this review, and withdrawn advisories are no longer returned by `npm audit`. SAFE PATH never accepts user-controlled glob patterns, `picomatch` is development-only, and the current audits report zero findings without proving that withdrawn advisory was fixed. CI keeps both audit commands enabled and separately requires `picomatch` to remain absent from the production dependency tree.

Provider behavior remains covered by deterministic mocked upstream tests. Ordinary CI does not call public OSM or Nominatim services. Native Docker, remote CI, and live Render behavior remain unverified because the repository was not pushed and no public resource was created.

## Phase 11 operations documentation

The deployment guide now covers local setup, production topology, Python 3.13, required deployment environment variables, PostgreSQL and migrations, static collection, Gunicorn, Docker, Render and Neon, superuser creation, health probes, logs, troubleshooting, provider policies, attribution, safety and routing limitations, and backup and recovery.

`docs/EXTERNAL_SERVICES.md` records the operator service inventory, privacy boundary, credential classes, provider agreement requirements, attribution duties, failure behavior, and provider-change checklist. It also states that the bundled incident file remains unverified demonstration data with unknown licensing and redistribution permission.

The documentation does not claim that a Render service, Neon database, CARTO account, paid road provider, or public deployment exists. Operator-managed backup and restore procedures use standard PostgreSQL and Python commands. The PostgreSQL dump, backup-list, and restore commands were exercised against a local PostgreSQL 16 container, and the SQLite backup command was exercised locally. No live production database was available for an end-to-end restore test.

A follow-up literal runbook review found and corrected several documentation defects: the production commands no longer use a rejected CARTO placeholder, the restored database is passed explicitly to `migrate --check`, the provider check states its inherited secret requirements, SQLite backup and restore honor `SAFEPATH_DATABASE_PATH`, route persistence is described accurately, and static-asset and mocked-provider checks include runnable commands. The production checks, production static collection, custom-path SQLite backup and restore, restored-database migration check, and 53 mocked provider tests were rerun successfully. The production check used an existing non-placeholder CI test value only to verify command execution; it does not establish CARTO ownership or provider connectivity.

A later CI and runbook review tightened the deployment gate so production requires PostgreSQL with an accepted TLS mode and trusted-proxy protocol handling, made SQLite backup and restore use Django's resolved database path, and limited live route smoke acceptance to successful routes or documented controlled provider errors. Required Blueprint validation now uses a checked-in Render schema snapshot, while a weekly and manually dispatched job checks the live schema. The checked-in and live schemas both validated the Blueprint. The strict production check passed with a PostgreSQL TLS configuration and rejected missing database or forwarded-protocol trust settings; the custom-path SQLite backup, restore, and backend checks passed; the controlled route-error smoke validation passed; and the native Gunicorn diagnostic smoke passed. These checks do not establish a Render service, a live database, provider connectivity, or public deployment.

## Phase 12 final acceptance

| Requirement | Executed evidence | Status |
| --- | --- | --- |
| Production web runtime | Gunicorn configuration check, native Gunicorn smoke test, and Podman container runtime | Passed locally |
| Docker no longer uses `runserver` | Image build, entrypoint inspection, and Gunicorn process inspection | Passed with Podman |
| Static asset collection and delivery | Production `collectstatic`, manifest verification, rendered URLs, CSS references, content types, and gzip checks | Passed locally |
| PostgreSQL and SQLite | 193 tests on each database, PostgreSQL 16 migrations, and `migrate --check` | Passed locally |
| Migration procedure | SQLite and PostgreSQL `migrate --noinput`, `migrate --check`, and Render startup command validation | Passed locally |
| Production secret, debug, host, CSRF, HTTPS, and cookie controls | Django deployment checks, production gate, and deployment regression tests | Passed; only deliberate HSTS warnings remain |
| External provider controls | Exact host allowlists, production road-provider approval, bounded requests, geocoder pacing and cache, and mocked upstream tests | Passed locally; live approved provider remains required |
| OSM and Nominatim attribution | Visible template and Leaflet attribution, browser regression tests, and provider documentation | Passed |
| Incident provenance | `data/source_metadata.json`, API allowlist, interface labels, and documentation | Passed; data remains unverified demonstration data |
| Unknown coverage and safety claims | Coverage union tests, unknown-risk API tests, and browser assertions | Passed |
| Existing routing, map, heatmap, and theme behavior | Django routing suite and 14 desktop and mobile Playwright tests | Passed |
| Python and frontend quality gates | Ruff lint and format, Mypy, compilation, Django checks, Tailwind, ESLint, and JavaScript syntax | Passed |
| Dependency audits | `pip-audit -r requirements.txt`, `npm audit --omit=dev`, and full `npm audit` | Current commands returned zero findings; withdrawn development-only `picomatch` advisory remains documented separately |
| GitHub Actions quality gates | Workflow YAML parse and Actionlint validation, checked-in Render schema test, and equivalent local gates executed | Local gates passed; remote run pending because no push was made |
| Docker build and health | Fresh upgraded-dependency Podman image build, migrations, health probe, non-root UID, static manifest, and graceful stop | Passed with Podman; native Docker daemon unavailable |
| Render configuration | Blueprint validated against the checked-in schema and `https://render.com/schema/render.yaml.json` on 2026-11-19 | Passed; no Render resource exists |
| Deployment and operations documentation | Link checks, PostgreSQL 16 dump and restore exercise, custom-path SQLite backup and restore exercise, diff check, and em-dash scan | Passed |
| Tailwind and reusable components | Tailwind build produced no committed CSS diff and browser regressions passed | Passed |

Repository preparation is complete for operator-managed deployment. Public deployment acceptance remains incomplete until the user creates the external resources, pushes the reviewed commits, runs GitHub Actions, applies the Blueprint, and performs the documented live smoke test.

## Baseline deployment posture at commit `9085090`

### Runtime and static files

- The Docker image starts `manage.py runserver` with `--insecure`.
- Django's development server currently serves application traffic and static files.
- Static assets have no production `STATIC_ROOT`, manifest, compression, or immutable-file configuration.
- The container starts migrations before every application start.
- The container runs as root.
- The image installs compiler packages and unused runtime packages that are not needed to run the application.
- The Compose service mounts the working tree and stores SQLite in the `safepath_data` named volume.

### Security configuration

Existing protections include:

- CSRF middleware and clickjacking middleware.
- Django `SecurityMiddleware`.
- A production secret key is required when debug mode is disabled.
- Debug mode defaults to disabled.
- Host and upstream host allowlists reject unconfigured destinations.
- External requests reject redirects and use finite timeouts.
- OSM graph construction enforces request, byte, area, XML element, depth, edge, and node limits.
- Route searches enforce a controlled exploration limit.
- API endpoints use DRF throttles.
- Graph and risk results are cached in process.

Gaps include:

- Loopback hosts are always added to `ALLOWED_HOSTS`, including production.
- HTTPS redirect, secure cookies, trusted origins, forwarded protocol, and HSTS are not configured.
- `/admin/` is publicly routed without a documented decision to retain it.
- Production logs are not configured.
- Raw upstream and routing failures need safer operational logging.
- The database URL and deployment secret values are not documented as a complete production configuration.

### Database limitations

- SQLite is the only supported database.
- PostgreSQL dependencies exist, but Django is not configured to use them.
- There is no `DATABASE_URL` parser, SSL configuration, connection lifetime, or connection health check.
- Session persistence and migrations have not been tested against PostgreSQL.
- Local Compose persistence works through a named volume, but the current CI startup assertion is failing.

### External service dependencies

- At baseline, road data came from `https://api.openstreetmap.org/api/0.6/map`, an editing API endpoint rather than a read-only production road service.
- Public Nominatim receives geocoding requests. The DRF throttle is process-local and does not enforce the public provider's application-wide one request per second policy.
- Geocoder results are not cached.
- OpenStreetMap standard tiles and CARTO dark tiles are loaded from public providers.
- Tile attribution is visible, but provider configuration and policy compliance are not documented.
- Public providers are not an availability guarantee for a public demonstration.

### Incident data limitations

- `data/delhi_crime_data.csv` contains 225 raw rows.
- The repository has no source metadata, collection methodology, collection date, license, or redistribution record.
- Git history shows the file was added in November 2025, but does not establish that its records are verified real-world incidents.
- Descriptions and coordinates look like manually assembled demonstration records. This is not proof of provenance and must not be presented as verified crime data.
- Risk coverage is currently inferred from a bounding rectangle around incident coordinates. That rectangle does not prove complete coverage of every road inside it.
- The safest label is conditional on the current coverage implementation, but the coverage semantics must be made explicit and conservative before public deployment.

### Routing and application limitations

- OSM turn restrictions are not applied, so the application is not turn-by-turn navigation software.
- The graph and risk model do not predict crime probability or personal safety.
- Travel time is an estimate from road class and speed data, not live traffic.
- OSM snapshots, geocoding, and map tiles depend on third-party availability.
- There is no custom account or incident reporting product. Django's framework-level admin support remains separate from those absent features.

## Planned changes

1. Replace the development server with Gunicorn and prepare a non-root production image.
2. Serve compressed, manifest-based static files through WhiteNoise.
3. Add `DATABASE_URL` support for PostgreSQL with SQLite as the local fallback.
4. Add environment-driven production security settings and validate `check --deploy`.
5. Replace the editing API road source with a permitted read-only provider, preserve request safeguards, and document provider policy.
6. Add global geocoder pacing, caching, attribution, and provider policy documentation.
7. Record verified incident metadata or explicitly mark the dataset as unverified demonstration data.
8. Replace inferred bounding-box coverage with conservative, explicit coverage semantics.
9. Audit routing correctness and performance without rewriting proven algorithms.
10. Improve health, logging, error responses, and operational diagnostics.
11. Add and validate a Render Blueprint and deployment guide.
12. Extend CI with production dependency, PostgreSQL, Gunicorn, static asset, and container gates.

## Acceptance criteria

Deployment readiness will require all of the following:

- Gunicorn is the production process and `runserver` is absent from production startup paths.
- WhiteNoise serves all required CSS, JavaScript, Leaflet, heatmap, marker, and favicon assets.
- SQLite remains the development fallback and PostgreSQL passes migrations and tests in CI.
- Production startup fails closed without a strong secret, explicit hosts, required HTTPS settings, and a customer-owned CARTO key.
- `manage.py check --deploy` has no unaddressed applicable warnings.
- Road and geocoding providers have documented policies, limits, caching, attribution, and failure behavior.
- Incident provenance and coverage limitations are visible in the interface and documentation.
- Routing, API, and browser regression tests remain green.
- The Docker image builds, starts under Gunicorn, becomes healthy, and serves static assets.
- Render configuration is valid against the current Blueprint specification.
- The GitHub Actions workflow passes on the final commit.

## Remaining risks

- The Render Blueprint has not created a live service. Render-specific networking, health checks, migrations, and TLS forwarding still require verification after the user deploys it.
- No Neon project, production database, customer-owned CARTO key, or Overpass.ch API key is configured in the repository.
- Public or hosted providers can throttle, reject, or become unavailable even when application safeguards work as designed.
- The production CARTO key must be customer-owned and domain-restricted before deployment.
- The incident dataset remains unverified demonstration data. Its source, methodology, date, license, and redistribution permission are unknown.
- Record-proximity coverage measures applicability of the bundled demonstration records, not real-world incident completeness or personal safety.
- Turn restrictions remain unsupported unless a selected provider and a correct route-search implementation make them feasible.
- The file-based geocoder limiter and cache coordinate workers only within one application instance. Multiple instances need external coordination or a self-hosted provider when using public Nominatim.
- A free hosted database may expire. An external PostgreSQL provider with an explicit retention policy is required for a durable demo.
- HSTS should remain disabled until the deployed hostname and HTTPS redirect path have been verified.
