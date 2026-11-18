# Deployment Readiness

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

- Road data comes from `https://api.openstreetmap.org/api/0.6/map`, an editing API endpoint rather than a read-only production road service.
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
- Production startup fails closed without a strong secret, explicit hosts, and required HTTPS settings.
- `manage.py check --deploy` has no unaddressed applicable warnings.
- Road and geocoding providers have documented policies, limits, caching, attribution, and failure behavior.
- Incident provenance and coverage limitations are visible in the interface and documentation.
- Routing, API, and browser regression tests remain green.
- The Docker image builds, starts under Gunicorn, becomes healthy, and serves static assets.
- Render configuration is valid against the current Blueprint specification.
- The GitHub Actions workflow passes on the final commit.

## Remaining risks

- Public or hosted providers can throttle, reject, or become unavailable even when application safeguards work as designed.
- The incident dataset cannot currently be treated as verified crime data.
- Bounding-box-derived coverage cannot establish complete road coverage.
- Turn restrictions remain unsupported unless a selected provider and a correct route-search implementation make them feasible.
- A single-process global geocoder limiter does not coordinate multiple application instances. A shared limiter is required if the deployment scales beyond one instance.
- A free hosted database may expire. An external PostgreSQL provider with an explicit retention policy is required for a durable demo.
- HSTS should remain disabled until the deployed hostname and HTTPS redirect path have been verified.
