# Deployment

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

## Production security

Production startup fails when `DJANGO_SECRET_KEY` is missing, shorter than 50 characters, insufficiently varied, starts with `django-insecure-`, or contains a known placeholder marker. Generate a new secret for every environment and store it in the platform secret manager:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Set `DJANGO_ALLOWED_HOSTS` to comma-separated exact host names without ports. Wildcard hosts are rejected in production, and loopback hosts are not added automatically. Set `DJANGO_CSRF_TRUSTED_ORIGINS` only for required cross-origin requests, using exact HTTPS origins without paths.

Production mode redirects HTTP to HTTPS and marks session and CSRF cookies secure. Gunicorn's own forwarded-scheme handling is disabled, but the raw header still reaches Django. Django ignores `X-Forwarded-Proto` by default and trusts it only when `DJANGO_TRUST_X_FORWARDED_PROTO=True` is set for a deployment whose trusted reverse proxy removes client-supplied forwarded headers and sets its own. Enable that flag whenever a TLS-terminating proxy fronts the application; otherwise the health probe reports an HTTPS redirect and user requests can enter a redirect loop. Do not expose Gunicorn directly to the public Internet. The included Compose service binds to `127.0.0.1` so only a local proxy can reach it.

HSTS remains disabled by default. After the deployed hostname, certificate, and HTTPS redirect path have been verified, set `DJANGO_SECURE_HSTS_SECONDS` to a deliberate lifetime. Enable `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` only when every subdomain supports HTTPS. Browser preload submission is a separate, explicit decision. The subdomain and preload options fail startup when the HSTS duration is zero.

Run the production checks with the same environment used by the deployment:

```bash
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY="$(cat /run/secrets/safepath_secret_key)" \
DJANGO_ALLOWED_HOSTS="safepath.example.com" \
SAFEPATH_CARTO_API_KEY="pk.REPLACE_WITH_REAL_CARTO_KEY" \
SAFEPATH_OSM_API_URL="https://road-provider.example/api/interpreter" \
SAFEPATH_OSM_API_ALLOWED_HOSTS="road-provider.example" \
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS="road-provider.example" \
python manage.py check --deploy
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY="$(cat /run/secrets/safepath_secret_key)" \
DJANGO_ALLOWED_HOSTS="safepath.example.com" \
SAFEPATH_CARTO_API_KEY="pk.REPLACE_WITH_REAL_CARTO_KEY" \
SAFEPATH_OSM_API_URL="https://road-provider.example/api/interpreter" \
SAFEPATH_OSM_API_ALLOWED_HOSTS="road-provider.example" \
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS="road-provider.example" \
python scripts/check_production.py
```

Django reports `security.W004` while HSTS is deliberately disabled. The production check script permits only the HSTS warnings `security.W004`, `security.W005`, and `security.W021`; every other warning or error fails the gate. It also requires explicit production approval for the road-data provider and rejects known public Overpass hosts.

## Static assets

Production uses `whitenoise.storage.CompressedManifestStaticFilesStorage` and collects files into `staticfiles/`. The Docker build performs this step automatically. A native production build must run:

```bash
DJANGO_SECRET_KEY="$(cat /run/secrets/safepath_secret_key)" \
DJANGO_DEBUG=False \
DJANGO_ALLOWED_HOSTS="safepath.example.com" \
SAFEPATH_CARTO_API_KEY="pk.REPLACE_WITH_REAL_CARTO_KEY" \
python manage.py collectstatic --noinput --clear --ignore "web/css/src/*"
```

The secret file must be readable only by the release process, so shell history records the file path rather than the secret value. Do not commit `staticfiles/`. Django templates resolve hashed asset URLs through the static tag. The committed Tailwind stylesheet and vendored Leaflet files are the collection source. CI uses `scripts/verify_static_assets.py` to fetch every required manifest URL, CSS image reference, and compressed response from the running service.

## Database

Set `DATABASE_URL` to a PostgreSQL URL for deployed environments:

```bash
DATABASE_URL='postgresql://safepath:url-encoded-password@db.example.com:5432/safepath?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-ca.pem'
```

The `postgres://` and `postgresql://` schemes are supported. Production URLs accept only PostgreSQL TLS query options: `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, and `sslcrl`. Certificate paths must exist in the runtime image or mounted secret store. Percent-encode reserved characters in credentials. When `DATABASE_URL` is unset, SAFE PATH uses SQLite at `SAFEPATH_DATABASE_PATH`.

Production mode rejects a PostgreSQL URL without `sslmode=require`, `verify-ca`, or `verify-full`. Prefer certificate verification. `require` encrypts the connection but does not authenticate the server certificate. The weaker `prefer`, `allow`, and `disable` modes are rejected. Production URLs reject every non-TLS query option so a secondary connection parameter cannot bypass the validated TLS mode or redirect the connection target.

PostgreSQL connections persist for `SAFEPATH_DATABASE_CONN_MAX_AGE` seconds, default `60`, and Django checks persistent connections before reuse. Run migrations against the same database before starting the release.

## Road data provider

The route loader uses an Overpass-compatible read-only endpoint. Configure all three values:

```bash
SAFEPATH_OSM_API_URL='https://road-provider.example/api/interpreter'
SAFEPATH_OSM_API_ALLOWED_HOSTS='road-provider.example'
SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS='road-provider.example'
```

The public `overpass-api.de` endpoint is a development fallback only. It has no availability guarantee and must not be used as the production road-data backend. Production requests require the provider host to appear in the explicit production approval list and reject known public Overpass hosts. `scripts/check_production.py` enforces the same requirement. The URL must use HTTPS, the host must appear in the exact allowlist, redirects are rejected, and URL credentials and non-standard ports are rejected. Listing a production host asserts that the operator has a paid or self-hosted agreement for it.

Each request uses fixed bounded Overpass QL. The loader limits provider requests, downloaded bytes, bounding-box area, split depth, XML depth, aggregate XML elements, graph edges, and the acquisition deadline checked between response reads. Provider requests are serialized within one process, and graphs are cached in process. See [DATA_PROVIDERS.md](DATA_PROVIDERS.md) for exact limits, licensing, attribution, and multi-instance constraints.

## Geocoding and map tiles

The geocoder uses a dedicated file-based cache under `SAFEPATH_CACHE_DIR`. In the container this is `/data/cache`, inside the persistent `safepath_data` volume. The application creates the directory with mode `0700` and rejects a public directory or symlink at startup because the cache backend deserializes local files. Gunicorn workers sharing that directory coordinate uncached requests through a file lock and start no more than one provider request per second. Provider responses are capped at 64 KiB. Cache hits do not consume provider capacity. Keep the deployment at one instance when using public Nominatim; separate instances do not share the lock and need external coordination or a self-hosted provider.

Production requires `SAFEPATH_CARTO_API_KEY`. Use a customer-owned, domain-restricted publishable key. Startup rejects obvious placeholder values. The value is sent directly from the browser to CARTO and is visible by design, so it is not a server secret and must not be stored as one. Do not proxy CARTO tiles through the application. Keep the visible Nominatim, OpenStreetMap, and CARTO attribution intact. Local development without a CARTO key uses filtered OpenStreetMap tiles instead of requesting a watermarked CARTO tile.

The application cannot verify provider plans, quotas, licenses, or availability. Review [DATA_PROVIDERS.md](DATA_PROVIDERS.md) before deploying with public providers.

## Migration modes

Choose one mode for each deployment:

| Mode | Configuration | Procedure |
| --- | --- | --- |
| Pre-deploy or release command | `SAFEPATH_RUN_MIGRATIONS=false` | Run `python manage.py migrate --noinput` once before starting the new release |
| Single-instance academic demo | `SAFEPATH_RUN_MIGRATIONS=true` | The container runs `python manage.py migrate --noinput` before starting Gunicorn |

Do not enable startup migrations when several application instances start from the same release at the same time. The pre-deploy mode prevents concurrent migration attempts. The startup mode is intended only for one application instance. The container accepts only the exact values `true` and `false`; any other value stops startup with exit code 64.

Migrations require a reachable database. They must never run as part of `docker build`.

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
