# Deployment

## Production architecture

SAFE PATH supports Python 3.13 and is tested with CPython 3.13.18. Node.js 22 is used to build frontend assets, not to serve the application.

A deployed topology has these trust boundaries:

```text
Browser -> TLS proxy or Render -> Gunicorn -> Django and DRF
                                      |-> WhiteNoise static assets
                                      |-> external PostgreSQL
                                      |-> approved road-data provider
                                      |-> approved geocoder
Browser -> OpenStreetMap or CARTO raster tiles
Django and Gunicorn -> bundled incident CSV
```

The application does not terminate TLS itself. The platform or proxy must terminate HTTPS and, when used, replace client-supplied forwarded headers. Gunicorn handles HTTP, WhiteNoise serves collected static files, and PostgreSQL stores framework state such as sessions and admin accounts. Route results, road graphs, and incident records are not persisted in the database. The incident CSV is bundled with the release.

Render's native Blueprint is an academic single-instance deployment. It uses one Gunicorn worker, an external PostgreSQL database, and an ephemeral local geocoder cache. No deployment or external resource is created by this repository.

## Local setup

Run these commands from a checkout:

```bash
python3.13 -m venv venv
. venv/bin/activate
pip install --requirement requirements-dev.txt
npm ci
cp .env.example .env
npm run build:css
DJANGO_DEBUG=True python manage.py migrate
DJANGO_DEBUG=True python manage.py runserver
```

Open <http://127.0.0.1:8000>. The public Overpass endpoint in `.env.example` is a low-volume development fallback with no availability guarantee. Local development does not require a CARTO key; without one, dark mode uses filtered OpenStreetMap tiles. SQLite is the local database fallback.

## Environment variables

[`.env.example`](../.env.example) is the complete supported environment inventory, and the README configuration table explains the main controls. A deployed environment must use these values:

| Variable | Deployment value | Handling |
| --- | --- | --- |
| `DJANGO_DEBUG` | `False` | Required production mode |
| `DJANGO_SECRET_KEY` | New random value with at least 50 varied characters | Secret manager; never commit |
| `DJANGO_ALLOWED_HOSTS` | Exact deployed host names, without ports | Required production allowlist |
| `CSRF_TRUSTED_ORIGINS` | Exact `https://` origins when cross-origin requests are needed | Exact HTTPS origins; no paths |
| `DJANGO_TRUST_X_FORWARDED_PROTO` | `True` only behind a proxy that replaces forwarded headers | Render uses `True`; keep `False` for direct local containers |
| `DATABASE_URL` | PostgreSQL URL with `sslmode=require`, `verify-ca`, or `verify-full` | Secret manager; use a direct URL for migrations |
| `SAFEPATH_CARTO_API_KEY` | Customer-owned publishable key restricted to the deployed domain | Browser-visible value, not a server secret |
| `SAFEPATH_OSM_API_URL` | HTTPS endpoint of the approved paid or self-hosted road provider | No URL credentials |
| `SAFEPATH_OSM_API_ALLOWED_HOSTS` | Exact host from `SAFEPATH_OSM_API_URL` | Exact host allowlist |
| `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS` | Same approved provider host | Explicit production assertion |
| `PORT` | Platform-assigned port | Gunicorn bind port |
| `SAFEPATH_CACHE_DIR` | Private application-owned directory with mode `0700` | Local cache; disposable on Render |

The production settings gate also validates the Django secret, hosts, any configured CSRF origins, forwarded-protocol choice, HTTPS cookies, PostgreSQL TLS settings, CARTO key, and road-provider approval. Run `python scripts/check_production.py` with the complete deployment environment before release.

## Application runtime

SAFE PATH runs under Gunicorn in the production container. The configuration reads:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | TCP port exposed by the web process |
| `GUNICORN_WORKERS` | `2` | Number of worker processes |
| `GUNICORN_TIMEOUT` | `60` | Worker request timeout in seconds |
| `GUNICORN_GRACEFUL_TIMEOUT` | `30` | Graceful shutdown timeout in seconds |
| `DOCKER_STOP_GRACE_PERIOD` | `40s` | Docker shutdown grace in integer seconds with an `s` suffix only; keep it greater than `GUNICORN_GRACEFUL_TIMEOUT` |
| `SAFEPATH_CACHE_DIR` | `/data/cache` in the image | Private geocoder cache and request-lock directory; must be owned by the application user with mode `0700` |

Gunicorn binds to `0.0.0.0` and forwards the configured graceful timeout when the platform sends a termination signal. The container redirects standard error to standard output before migrations and Gunicorn start, so all container process logs use one stream. Startup fails with exit code 64 unless the Gunicorn grace is integer seconds, the Docker stop grace uses the same integer-second format with an `s` suffix, and the Docker stop grace is greater than the Gunicorn graceful timeout. Docker must therefore allow more time than Gunicorn's graceful timeout or it can terminate workers before graceful shutdown finishes.

The container runs as the unprivileged `safepath` user. It does not include `.env` files and does not run migrations during the image build. The image build runs `collectstatic`, and WhiteNoise serves compressed, manifest-based assets from the production runtime.

## Health checks and logs

`/health/` and `/health/live/` are liveness endpoints. They only confirm that Django can serve a request. They do not query the database, construct a road graph, or call OSM or Nominatim. `/health/ready/` runs a database `SELECT 1` and returns HTTP 503 when the database is unavailable. Keep liveness and readiness paths separate so a database outage does not cause the platform to restart an otherwise healthy web process.

Application logs use standard output and standard error. Gunicorn access logs contain the HTTP method, path without its query string, status, response size, and duration. Error logs contain the route pattern, error code, and exception type. Django, third-party, and Gunicorn errors use the same safe formatter. It removes URL query strings and credentials, redacts sensitive assignments, and replaces exception messages. Expected API validation failures are not repeated as server errors.

Inspect logs with:

```bash
docker compose logs django
```

Render exposes service logs in its dashboard. Alert on repeated HTTP 503 responses, readiness failures, and `internal_error` events. Provider failures can be transient, so confirm the configured provider status before changing application configuration.

## Production security

Production startup fails when `DJANGO_SECRET_KEY` is missing, shorter than 50 characters, insufficiently varied, starts with `django-insecure-`, or contains a known placeholder marker. Generate a new secret for every environment and store it in the platform secret manager:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Set `DJANGO_ALLOWED_HOSTS` to comma-separated exact host names without ports. Wildcard hosts are rejected in production, and loopback hosts are not added automatically. Set `CSRF_TRUSTED_ORIGINS` only for required cross-origin requests, using exact HTTPS origins without paths. `DJANGO_CSRF_TRUSTED_ORIGINS` remains accepted as a legacy alias.

Production mode redirects HTTP to HTTPS and marks session and CSRF cookies secure. Gunicorn's own forwarded-scheme handling is disabled, but the raw header still reaches Django. Django ignores `X-Forwarded-Proto` by default and trusts it only when `DJANGO_TRUST_X_FORWARDED_PROTO=True` is set for a deployment whose trusted reverse proxy removes client-supplied forwarded headers and sets its own. Enable that flag whenever a TLS-terminating proxy fronts the application; otherwise the health probe reports an HTTPS redirect and user requests can enter a redirect loop. Do not expose Gunicorn directly to the public Internet. The included Compose service binds to `127.0.0.1` so only a local proxy can reach it.

HSTS remains disabled by default. After the deployed hostname, certificate, and HTTPS redirect path have been verified, set `DJANGO_SECURE_HSTS_SECONDS` to a deliberate lifetime. Enable `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` only when every subdomain supports HTTPS. Browser preload submission is a separate, explicit decision. The subdomain and preload options fail startup when the HSTS duration is zero.

Run the production checks with the same environment used by the deployment. The shell must already contain the operator-provided Django secret, customer-owned CARTO key, deployed host, production PostgreSQL URL, and approved road-provider values from the platform environment. Do not substitute placeholder values; production settings intentionally reject them.

```bash
: "${DJANGO_SECRET_KEY:?Export the operator-provided Django secret}"
: "${SAFEPATH_CARTO_API_KEY:?Export the customer-owned CARTO key}"
: "${DJANGO_ALLOWED_HOSTS:?Export the exact deployed host list}"
: "${DATABASE_URL:?Export the production PostgreSQL URL}"
: "${SAFEPATH_OSM_API_URL:?Export the approved provider URL}"
: "${SAFEPATH_OSM_API_ALLOWED_HOSTS:?Export the approved provider host}"
: "${SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS:?Export the approved provider host}"

export DJANGO_SECRET_KEY
export SAFEPATH_CARTO_API_KEY
export DJANGO_ALLOWED_HOSTS
export DATABASE_URL
export SAFEPATH_OSM_API_URL
export SAFEPATH_OSM_API_ALLOWED_HOSTS
export SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS
export DJANGO_DEBUG=False
python manage.py check --deploy
python scripts/check_production.py
```

Django reports `security.W004` while HSTS is deliberately disabled. The production check script permits only the HSTS warnings `security.W004`, `security.W005`, and `security.W021`; every other warning or error fails the gate. It also requires explicit production approval for the road-data provider and rejects known public Overpass hosts.

## Dependency audits

Audit the pinned production Python environment and the frontend production dependency set:

```bash
pip-audit --requirement requirements.txt --progress-spinner off
npm audit --omit=dev
```

Both commands must complete without findings. An earlier full `npm audit` run reported two high-severity development-tool findings through Tailwind's transitive `@parcel/watcher` and `picomatch` packages. The `picomatch` advisory, `GHSA-fc5q-39xc-vjpf`, was withdrawn on 2026-11-18 after the upstream maintainer determined that the reported regular-expression denial of service requires attacker-controlled glob patterns. No patched upstream `picomatch` release was available during this review, and withdrawn advisories are no longer returned by `npm audit`. SAFE PATH never accepts user-controlled glob patterns, `picomatch` is development-only, and the current audits report zero findings without proving that withdrawn advisory was fixed. CI keeps both audit commands enabled and separately requires `picomatch` to remain absent from the production dependency tree.

The affected development code would run only during local and CI Tailwind glob matching with repository-controlled paths, and it is not installed as a production application dependency. Do not apply `npm audit fix --force`, and do not replace the pinned Tailwind toolchain with an unverified major version. Any new finding must fail review until its exposure and mitigation are documented.

## Static assets

Production uses `whitenoise.storage.CompressedManifestStaticFilesStorage` and collects files into `staticfiles/`. The Docker build performs this step automatically. With the complete production environment exported as described above, a native production build must run:

```bash
python manage.py collectstatic --noinput --clear --ignore "web/css/src/*"
```

The environment's secret values must come from the release secret store so shell history records only variable names. Do not commit `staticfiles/`. Django templates resolve hashed asset URLs through the static tag. The committed Tailwind stylesheet and vendored Leaflet files are the collection source. CI uses `scripts/verify_static_assets.py` to fetch every required manifest URL, CSS image reference, and compressed response from the running service.

## Database

Set `DATABASE_URL` to a PostgreSQL URL for deployed environments:

```bash
DATABASE_URL='postgresql://safepath:url-encoded-password@db.example.com:5432/safepath?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-ca.pem'
```

The `postgres://` and `postgresql://` schemes are supported. Production URLs accept only PostgreSQL TLS query options: `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, and `sslcrl`. Certificate paths must exist in the runtime image or mounted secret store. Percent-encode reserved characters in credentials. Local development and Compose use SQLite at `SAFEPATH_DATABASE_PATH` when `DATABASE_URL` is unset. The Render startup command runs `scripts/check_production.py`, which rejects a missing PostgreSQL URL before migrations or Gunicorn start.

Production mode rejects a PostgreSQL URL without `sslmode=require`, `verify-ca`, or `verify-full`. Prefer certificate verification. `require` encrypts the connection but does not authenticate the server certificate. The weaker `prefer`, `allow`, and `disable` modes are rejected. Production URLs reject every non-TLS query option so a secondary connection parameter cannot bypass the validated TLS mode or redirect the connection target.

PostgreSQL connections persist for `SAFEPATH_DATABASE_CONN_MAX_AGE` seconds, default `60`, and Django checks persistent connections before reuse. Connection establishment is limited to five seconds and statements to ten seconds, keeping readiness checks and failed connections below the Gunicorn worker timeout. Run migrations against the same database before starting the release.

### Admin and superuser

Django's framework admin remains enabled at `/admin/`. It is an operator tool, not a SAFE PATH user-account system, and it has no SAFE PATH-specific access controls. If it is not needed, block the path at the hosting proxy or remove it in a separately reviewed deployment change.

Create a superuser with the complete production environment and a direct PostgreSQL URL:

```bash
python manage.py createsuperuser
```

The command uses the active `DATABASE_URL` and writes only the standard Django auth rows. Render Free has no shell, so run it from a trusted operator checkout connected to the same database. Keep the password out of command history and deployment logs. After creation, test the login at `https://YOUR-HOSTNAME/admin/` and remove any temporary database access that is no longer required.

### Backup and recovery

The database contains framework sessions, admin accounts, and Django administrative history. It does not contain routes, graphs, cached responses, or incident records. Incident data and application source come from the reviewed Git release; static files are rebuilt with `collectstatic`; local graph and geocoder caches are disposable.

Use the database provider's scheduled snapshots or point-in-time recovery as the primary backup. Test a restore before relying on it. A PostgreSQL logical backup can also be created from an operator workstation:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require'
backup_file="safepath-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --dbname="$DATABASE_URL" --format=custom --file="$backup_file"
pg_restore --list "$backup_file"
```

Protect the backup file because it contains session and administrator data. Encrypt it at rest and restrict access. Restore into an isolated database first:

```bash
export DIRECT_DATABASE_URL='postgresql://USER:PASSWORD@HOST/RESTORE_DATABASE?sslmode=require'
pg_restore \
  --dbname="$DIRECT_DATABASE_URL" \
  --clean \
  --if-exists \
  --no-owner \
  --exit-on-error \
  safepath-YYYYMMDDTHHMMSSZ.dump
```

Stop application instances before restoring over an existing database. After restore, run `migrate --check` against the restored database with the complete production environment exported:

```bash
DATABASE_URL="$DIRECT_DATABASE_URL" python manage.py migrate --check
```

Then start one instance, verify `/health/ready/`, and test admin login. A successful database restore does not restore provider availability or the incident dataset.

For local SQLite, use Python's online backup API instead of copying a live database file. Run these commands from the checkout root. `manage.py` loads `.env`, and Django resolves the same absolute SQLite path used by the application, including `SAFEPATH_DATABASE_PATH` and the default `BASE_DIR/db.sqlite3`:

```bash
DATABASE_URL= DJANGO_DEBUG=True python manage.py shell <<'PY'
import os
import sqlite3
from pathlib import Path

from django.conf import settings

database = settings.DATABASES["default"]
if database["ENGINE"] != "django.db.backends.sqlite3":
    raise SystemExit("The active application database is not SQLite.")

source_path = Path(database["NAME"])
backup_path = Path(
    os.environ.get("SAFEPATH_SQLITE_BACKUP_PATH") or f"{source_path}.backup"
).expanduser().resolve()
if not source_path.is_file():
    raise SystemExit(f"SQLite database does not exist: {source_path}")

source = sqlite3.connect(source_path)
target = sqlite3.connect(backup_path)
with target:
    source.backup(target)
target.close()
source.close()
print(f"SQLite backup written to {backup_path}")
PY
```

Restore only while application instances are stopped. Set `SAFEPATH_SQLITE_BACKUP_PATH` to the path printed by the backup command, or to the verified backup location. This replaces the configured SQLite database with the backup contents:

```bash
: "${SAFEPATH_SQLITE_BACKUP_PATH:?Set the path to the verified SQLite backup}"
DATABASE_URL= DJANGO_DEBUG=True python manage.py shell <<'PY'
import os
import sqlite3
from pathlib import Path

from django.conf import settings

database = settings.DATABASES["default"]
if database["ENGINE"] != "django.db.backends.sqlite3":
    raise SystemExit("The active application database is not SQLite.")

source_path = Path(os.environ["SAFEPATH_SQLITE_BACKUP_PATH"]).expanduser().resolve()
target_path = Path(database["NAME"])
if not source_path.is_file():
    raise SystemExit(f"SQLite backup does not exist: {source_path}")

source = sqlite3.connect(source_path)
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
target.close()
source.close()
PY
```

After restoring, validate the SQLite database rather than an inherited PostgreSQL URL:

```bash
DATABASE_URL= DJANGO_DEBUG=True python manage.py migrate --check
```

Then start one instance and verify `/health/ready/`.

## Road data provider

The route loader uses an Overpass-compatible read-only endpoint. Configure all three values:

```bash
SAFEPATH_OSM_API_URL='https://road-provider.example/api/interpreter'
SAFEPATH_OSM_API_ALLOWED_HOSTS='road-provider.example'
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS='road-provider.example'
```

These are reserved example values. Replace them with the operator's approved provider URL and exact host.

The public `overpass-api.de` endpoint is a development fallback only. It has no availability guarantee and must not be used as the production road-data backend. Production requests require the provider host to appear in the explicit production approval list and reject known public Overpass hosts. `scripts/check_production.py` enforces the same requirement. The URL must use HTTPS, the host must appear in the exact allowlist, redirects are rejected, and URL credentials and non-standard ports are rejected. Listing a production host asserts that the operator has a paid or self-hosted agreement for it.

Each request uses fixed bounded Overpass QL. The loader limits provider requests, downloaded bytes, bounding-box area, split depth, XML depth, aggregate XML elements, graph edges, and the acquisition deadline checked between response reads. Provider requests are serialized within one process, and graphs are cached in process. See [DATA_PROVIDERS.md](DATA_PROVIDERS.md) for exact limits, licensing, attribution, and multi-instance constraints.

## Geocoding and map tiles

The geocoder uses a dedicated file-based cache under `SAFEPATH_CACHE_DIR`. In the container this is `/data/cache`, inside the persistent `safepath_data` volume. The application creates the directory with mode `0700` and rejects a public directory or symlink at startup because the cache backend deserializes local files. Gunicorn workers sharing that directory coordinate uncached requests through a file lock and start no more than one provider request per second. Provider responses are capped at 64 KiB. Cache hits do not consume provider capacity. Keep the deployment at one instance when using public Nominatim; separate instances do not share the lock and need external coordination or a self-hosted provider.

Production requires `SAFEPATH_CARTO_API_KEY`. Use a customer-owned, domain-restricted publishable key. Startup rejects obvious placeholder values. The value is sent directly from the browser to CARTO and is visible by design, so it is not a server secret and must not be stored as one. Do not proxy CARTO tiles through the application. Keep the visible Nominatim, OpenStreetMap, and CARTO attribution intact. Local development without a CARTO key uses filtered OpenStreetMap tiles instead of requesting a watermarked CARTO tile.

The application cannot verify provider plans, quotas, licenses, or availability. Review [DATA_PROVIDERS.md](DATA_PROVIDERS.md) before deploying with public providers. The operator checklist is in [EXTERNAL_SERVICES.md](EXTERNAL_SERVICES.md).

## Attribution and provider policies

Keep the visible Nominatim, OpenStreetMap, and CARTO attribution intact. OpenStreetMap road data is available under the Open Database License, and the standard raster tile service has its own acceptable-use policy. Nominatim requires an identifying User-Agent, caching, no autocomplete, valid attribution, and no more than one request per second on the public service. CARTO basemap use is governed by the customer's plan and attribution terms. Do not replace a provider without repeating its licensing and attribution review.

The technical configuration and request limits are documented in [DATA_PROVIDERS.md](DATA_PROVIDERS.md). The service inventory, credential classes, privacy boundary, failure behavior, and provider-change checklist are documented in [EXTERNAL_SERVICES.md](EXTERNAL_SERVICES.md).

## Safety and routing limitations

The bundled incident file is unverified demonstration data. Its original source, collection methodology, collection date, geographical coverage, license, and redistribution permission are unknown. It is not a live police or emergency feed. Confirm its license and redistribution permission before use beyond this academic demonstration.

The reported record score is deterministic proximity to bundled demonstration records. It does not estimate crime probability, personal safety, or an individual's risk. Travel time comes from road class and available speed data, not live traffic. Record-proximity coverage measures whether a route lies within 200 metres of the bundled records; it does not establish real-world incident completeness. Partial or uncovered routes remain unrated, and the application does not assign a safest label without a fully covered eligible candidate.

Road graphs are bounded snapshots from the selected provider. They do not apply OSM turn restrictions or relation-based restrictions, do not include live closures or traffic, and may differ from a turn-by-turn navigation service. Endpoint snapping and route diversity thresholds can affect candidates. At most four unique routes are returned, and fewer may exist when the graph does not support distinct connected paths.

## Migration modes

Choose one mode for each deployment:

| Mode | Configuration | Procedure |
| --- | --- | --- |
| Pre-deploy or release command | `SAFEPATH_RUN_MIGRATIONS=false` | Run `python manage.py migrate --noinput` once before starting the new release |
| Single-instance academic demo | `SAFEPATH_RUN_MIGRATIONS=true` | The container runs `python manage.py migrate --noinput` before starting Gunicorn |

Do not enable startup migrations when several application instances start from the same release at the same time. The pre-deploy mode prevents concurrent migration attempts. The startup mode is intended only for one application instance. The container accepts only the exact values `true` and `false`; any other value stops startup with exit code 64.

Migrations require a reachable database. They must never run as part of `docker build`.

## Render native deployment

The repository includes `render.yaml` for Render's native Python runtime. The Blueprint uses one Free web service in Singapore, Python 3.13.18, the `main` branch, `/health/` for platform health checks, one Gunicorn worker, and a 40 second shutdown allowance. It does not create a Render PostgreSQL database.

Render's Free web service is an academic demonstration option, not a production deployment. It has one instance, an ephemeral filesystem, no pre-deploy command, and no shell. A service without inbound traffic can spin down after 15 minutes and can take about one minute to start again. The local geocoder cache is therefore disposable. Keep session, admin, and framework state in external PostgreSQL.

### Required provider and database values

Prepare these values before creating the Blueprint:

| Variable | Required value |
| --- | --- |
| `DJANGO_ALLOWED_HOSTS` | Exact Render hostname, without a scheme or port |
| `CSRF_TRUSTED_ORIGINS` | Exact `https://` origin for the same hostname |
| `DATABASE_URL` | PostgreSQL URL for the demo database with `sslmode=require`, `verify-ca`, or `verify-full` |
| `SAFEPATH_CARTO_API_KEY` | Customer-owned, domain-restricted CARTO publishable key |
| `SAFEPATH_OSM_API_URL` | HTTPS endpoint of the approved paid or self-hosted Overpass-compatible provider |
| `SAFEPATH_OSM_API_ALLOWED_HOSTS` | Exact host from `SAFEPATH_OSM_API_URL` |
| `SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS` | Same exact provider host, explicitly approved for production |

Render generates `DJANGO_SECRET_KEY` from `generateValue: true`. Do not replace it with a committed value. The Blueprint sets `DJANGO_DEBUG=False`, trusts Render's TLS forwarding header, and provides bounded provider timeouts, cache limits, and API throttle rates. Render supplies `PORT`; the start command binds Gunicorn to that value.

Public Overpass and Nominatim endpoints have no availability guarantee. The production gate rejects known public road providers even when they appear in the approval list. A public demonstration remains blocked until an approved road provider and a real CARTO key are available.

### Neon setup

Use an external PostgreSQL provider such as Neon instead of Render Free PostgreSQL. Render Free PostgreSQL expires after 30 days and is not a durable demo database.

1. Create a Neon project, branch, database, and application role.
2. Copy the direct PostgreSQL connection string. Do not use the pooled endpoint for the supplied start command because startup migrations can require direct connections.
3. Keep or add `sslmode=require` in the URL. Remove query options that the application does not support. Percent-encode reserved characters in the password.
4. Store the complete URL only in Render's environment variable prompt. Do not put it in `render.yaml`, `.env`, a shell command, or a commit.

The URL must have this form:

```text
postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

Neon may provide a direct endpoint and a pooled endpoint with a `-pooler` hostname. The direct endpoint is required for the default startup migration flow. A paid Render deployment can run migrations in `preDeployCommand` and can then use a pooled endpoint for application traffic if its PostgreSQL driver and session behavior have been verified.

### Create the Blueprint service

1. Push the reviewed deployment commits to `main`. This preparation does not create or deploy any Render resource.
2. In the Render dashboard, select **New**, then **Blueprint**, and connect `https://github.com/K2K22K2K22/SafePath`.
3. Select the `main` branch and review the single `safepath` web service.
4. Enter each prompted value from the table above. For a service named `safepath`, use `safepath.onrender.com` only if Render assigns that hostname. If the dashboard assigns a different hostname, update both host variables before testing requests.
5. Apply the Blueprint. Render creates the service, generates the Django secret, installs `requirements.txt`, and collects static files.
6. Wait for the deploy to finish, then inspect the service logs for migration completion and Gunicorn startup.
7. Confirm the public hostname from the Render dashboard, then verify:

```bash
BASE_URL='https://YOUR-HOSTNAME'

curl -fsS "$BASE_URL/health/"
curl -fsS "$BASE_URL/health/ready/"

asset_path="$(
  curl --fail --silent --show-error "$BASE_URL/" \
    | grep -o '/static/[^"[:space:]]*\.css' \
    | head -n 1
)"
test -n "$asset_path"
curl --fail-with-body --silent --show-error "$BASE_URL$asset_path" --output /dev/null
```

The health requests must return `{"status":"ok"}` and `{"status":"ready"}`. The extracted stylesheet request must succeed and use the hashed manifest URL.

### Build, migration, and process behavior

The native build command installs only `requirements.txt` and runs:

```bash
python manage.py collectstatic --noinput --ignore "web/css/src/*"
```

The committed Tailwind stylesheet and vendored Leaflet files are the static source. No Node build is required during a Render deploy.

The Free start command validates production configuration, applies migrations, and then starts Gunicorn:

```bash
python scripts/check_production.py &&
python manage.py migrate --noinput &&
gunicorn safepath_backend.wsgi:application --config gunicorn.conf.py \
  --bind "0.0.0.0:${PORT:-10000}" --workers 1 --timeout 60 \
  --graceful-timeout 30
```

The production check fails startup when PostgreSQL, TLS, provider approval, or another required deployment value is missing. Free services cannot run `preDeployCommand`. Startup migrations are therefore acceptable only for this single-instance demo. Do not scale the service until migrations move to a paid plan's pre-deploy command or an equivalent single migration job. Moving to a paid plan requires changing the plan, adding `preDeployCommand: python manage.py migrate --noinput`, and removing `python manage.py migrate --noinput` from `startCommand` while retaining the production check before Gunicorn starts.

Keep the service at one instance while using public Nominatim. Its file-based pacing lock coordinates workers inside one instance but not separate Render instances. Use an approved geocoder or external shared coordination before scaling.

### Blueprint validation

Required CI validates the Blueprint against the checked-in schema snapshot, so a Render outage or upstream schema change cannot block unrelated pull requests:

```bash
pip install --requirement requirements-dev.txt
python scripts/validate_render.py render.yaml --schema schemas/render.schema.json
```

Before deployment, also validate against Render's current live schema:

```bash
python scripts/validate_render.py render.yaml
```

The live command fetches `https://render.com/schema/render.yaml.json`. The scheduled weekly workflow and manual workflow dispatch run this check. The checked-in snapshot was retrieved on 2026-11-19 and has SHA-256 `6c6721a602ef6d368d5c9384c473cefaae99980e43dd4b1adcf8a2f258fc54f4`. Refresh it and review the diff when Render changes the schema:

```bash
set -euo pipefail
curl --fail --silent --show-error --location --max-time 30 \
  https://render.com/schema/render.yaml.json \
  --output schemas/render.schema.json
python scripts/validate_render.py render.yaml --schema schemas/render.schema.json
```

The repository also contains a deterministic Blueprint configuration test.

### Troubleshooting

- A redirect from `/health/` indicates that the forwarded protocol was not recognized. Confirm that `DJANGO_TRUST_X_FORWARDED_PROTO=True` remains set for the Render-only deployment.
- `DisallowedHost` indicates that `DJANGO_ALLOWED_HOSTS` does not exactly match the hostname used in the request.
- A database startup error usually means that `DATABASE_URL` is missing, uses a non-PostgreSQL scheme, lacks required TLS, or contains an unsupported query option.
- `road_provider_unavailable` means that the configured provider is unavailable or that its exact host is not approved. It does not fall back to a different provider.
- A missing CARTO key or an obvious placeholder causes production startup to fail. Use a real customer-owned key restricted to the deployed domain.
- The geocoder cache and all other local files disappear after a restart or redeploy. This is expected on Render's ephemeral filesystem.

### Optional live smoke test

Run this procedure manually after deployment. It is not part of ordinary CI because the geocoding and route checks call external providers.

```bash
set -eu
BASE_URL='https://YOUR-HOSTNAME'

curl --fail-with-body --silent --show-error "$BASE_URL/health/"
curl --fail-with-body --silent --show-error "$BASE_URL/health/ready/"
curl --fail-with-body --silent --show-error "$BASE_URL/api/safety-heatmap/"
curl --fail-with-body --silent --show-error \
  "$BASE_URL/api/geocode/?q=Connaught%20Place%20Delhi"

route_status="$(
  curl --silent --show-error \
    --output /tmp/safepath-route-response.json \
    --write-out '%{http_code}' \
    "$BASE_URL/api/routes/?start_lat=28.4748&start_lon=77.4764&end_lat=28.48&end_lon=77.482"
)"
python - "$route_status" /tmp/safepath-route-response.json <<'PY'
import json
import sys
from pathlib import Path

status = int(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if 200 <= status < 300:
    routes = payload.get("routes")
    assert isinstance(routes, list), payload
    assert routes, payload
    assert payload.get("route_count") == len(routes), payload
else:
    expected_codes = {
        "route_not_found",
        "road_provider_unavailable",
        "search_limit_exceeded",
        "rate_limit_exceeded",
    }
    assert status in {404, 429, 503}, (status, payload)
    assert payload.get("code") in expected_codes, payload
assert "traceback" not in json.dumps(payload).lower(), payload
PY

asset_path="$(
  curl --fail --silent --show-error "$BASE_URL/" \
    | grep -o '/static/[^"[:space:]]*\.css' \
    | head -n 1
)"
test -n "$asset_path"
curl --fail-with-body --silent --show-error "$BASE_URL$asset_path" --output /dev/null
```

The health checks must return `{"status":"ok"}` and `{"status":"ready"}`. The heatmap and geocoder responses must be valid JSON. A successful route response must contain at least one route. A controlled HTTP 404, 429, or 503 response is accepted only for the documented route error codes checked above; `internal_error` and tracebacks fail the smoke test. Inspect Render logs for provider failures, readiness errors, and `internal_error` events.

Repeat the test after a cold start to confirm that the service and readiness check recover while the external database remains reachable. This procedure does not prove row-level database persistence and does not inspect whether local cache files were recreated. Verify persistence separately through the database provider's backup and restore procedure, and inspect the filesystem directly if cache recreation must be verified.

## Docker

Prepare the environment and start the single-instance Compose service:

```bash
cp .env.example .env
# Set a strong DJANGO_SECRET_KEY and a domain-restricted SAFEPATH_CARTO_API_KEY in .env
# Set the paid or self-hosted road provider approval in .env
docker compose up --build
```

Compose starts Gunicorn on `PORT` (default `8000`), binds it to `127.0.0.1`, runs migrations because `SAFEPATH_RUN_MIGRATIONS` defaults to `true`, and stores SQLite and the geocoder cache in the `safepath_data` named volume. Its short-lived `data-init` service changes that volume to UID and GID `10001` before the non-root application starts, including when upgrading a volume created by an older root-owned image. The image contains the application source, so rebuild it after a source change. The container health probe sends the first configured production host instead of an implicit loopback host. Compose uses production security settings, so route requests require a paid or self-hosted road-data provider explicitly approved in `.env`, and the dark basemap requires a customer-owned CARTO key.

Check the service:

```bash
docker compose exec django python /app/scripts/healthcheck.py
docker compose logs django
```

Stop the service without deleting the database volume:

```bash
docker compose down
```

Delete the local database volume only when the stored data is intentionally disposable:

```bash
docker compose down --volumes
```

## Direct container command

The image reads `PORT` and starts Gunicorn after the selected migration step:

```bash
docker build --tag safepath .
docker run --rm --publish "127.0.0.1:${PORT:-8000}:${PORT:-8000}" \
  --stop-timeout 40 \
  --env-file .env \
  --env PORT="${PORT:-8000}" \
  --env DJANGO_DEBUG=False \
  --env DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1" \
  --env DJANGO_TRUST_X_FORWARDED_PROTO=False \
  --env SAFEPATH_CACHE_DIR=/data/cache \
  --env SAFEPATH_DATABASE_PATH=/data/db.sqlite3 \
  --env SAFEPATH_RUN_MIGRATIONS=true \
  --env GUNICORN_GRACEFUL_TIMEOUT=30 \
  --env DOCKER_STOP_GRACE_PERIOD=40s \
  --volume safepath_data:/data \
  safepath
```

Do not pass a production secret directly on a shared shell history. Use the platform's secret manager or an ignored environment file for local evaluation. The direct command binds to loopback and keeps forwarded-header trust disabled. Put a TLS-terminating proxy in front of it, and enable forwarded-header trust only in that proxy deployment. The image cannot encode a Docker stop timeout, so direct `docker run` commands must pass `--stop-timeout` with the same number of seconds as `DOCKER_STOP_GRACE_PERIOD`. A direct container using a volume created by an older root-owned image needs a one-time ownership repair before it can start as the non-root user:

```bash
docker run --rm --user root \
  --volume safepath_data:/data \
  safepath chown -R 10001:10001 /data
```
