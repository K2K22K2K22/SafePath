# Deployment

## Application runtime

SAFE PATH runs under Gunicorn in the production container. The configuration reads:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | TCP port exposed by the web process |
| `GUNICORN_WORKERS` | `2` | Number of worker processes |
| `GUNICORN_TIMEOUT` | `60` | Worker request timeout in seconds |
| `GUNICORN_GRACEFUL_TIMEOUT` | `30` | Graceful shutdown timeout in seconds |
| `DOCKER_STOP_GRACE_PERIOD` | `40s` | Docker shutdown grace period; keep it greater than `GUNICORN_GRACEFUL_TIMEOUT` |

Gunicorn binds to `0.0.0.0` and forwards the configured graceful timeout when the platform sends a termination signal. The container redirects standard error to standard output before migrations and Gunicorn start, so all container process logs use one stream. Startup fails with exit code 64 unless both grace values are integer seconds and the Docker stop grace is greater than the Gunicorn graceful timeout. Docker must therefore allow more time than Gunicorn's graceful timeout or it can terminate workers before graceful shutdown finishes.

The container runs as the unprivileged `safepath` user. It does not include `.env` files and does not run migrations during the image build. The image build runs `collectstatic`, and WhiteNoise serves compressed, manifest-based assets from the production runtime.

## Static assets

Production uses `whitenoise.storage.CompressedManifestStaticFilesStorage` and collects files into `staticfiles/`. The Docker build performs this step automatically. A native production build must run:

```bash
DJANGO_SECRET_KEY="$(cat /run/secrets/safepath_secret_key)" \
DJANGO_DEBUG=False \
DJANGO_ALLOWED_HOSTS="safepath.example.com" \
python manage.py collectstatic --noinput --clear --ignore "web/css/src/*"
```

The secret file must be readable only by the release process, so shell history records the file path rather than the secret value. Do not commit `staticfiles/`. Django templates resolve hashed asset URLs through the static tag. The committed Tailwind stylesheet and vendored Leaflet files are the collection source. CI uses `scripts/verify_static_assets.py` to fetch every required manifest URL, CSS image reference, and compressed response from the running service.

## Database

Set `DATABASE_URL` to a PostgreSQL URL for deployed environments:

```bash
DATABASE_URL='postgresql://safepath:url-encoded-password@db.example.com:5432/safepath?sslmode=require'
```

The `postgres://` and `postgresql://` schemes are supported. URL query options are passed to PostgreSQL, including `sslmode` and `sslrootcert`. Certificate paths must exist in the runtime image or mounted secret store. Percent-encode reserved characters in credentials. When `DATABASE_URL` is unset, SAFE PATH uses SQLite at `SAFEPATH_DATABASE_PATH`.

PostgreSQL connections persist for `SAFEPATH_DATABASE_CONN_MAX_AGE` seconds, default `60`, and Django checks persistent connections before reuse. Run migrations against the same database before starting the release.

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
# Set a strong DJANGO_SECRET_KEY in .env
docker compose up --build
```

Compose starts Gunicorn on `PORT` (default `8000`), runs migrations because `SAFEPATH_RUN_MIGRATIONS` defaults to `true`, and stores SQLite in the `safepath_data` named volume. Its short-lived `data-init` service changes that volume to UID and GID `10001` before the non-root application starts, including when upgrading a volume created by an older root-owned image. The image contains the application source, so rebuild it after a source change.

Check the service:

```bash
curl --fail http://127.0.0.1:8000/health/
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
docker run --rm --publish "${PORT:-8000}:${PORT:-8000}" \
  --stop-timeout 40 \
  --env-file .env \
  --env PORT="${PORT:-8000}" \
  --env DJANGO_DEBUG=False \
  --env DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1" \
  --env SAFEPATH_DATABASE_PATH=/data/db.sqlite3 \
  --env SAFEPATH_RUN_MIGRATIONS=true \
  --env GUNICORN_GRACEFUL_TIMEOUT=30 \
  --env DOCKER_STOP_GRACE_PERIOD=40s \
  --volume safepath_data:/data \
  safepath
```

Do not pass a production secret directly on a shared shell history. Use the platform's secret manager or an ignored environment file for local evaluation. A direct container using a volume created by an older root-owned image needs a one-time ownership repair before it can start as the non-root user:

```bash
docker run --rm --user root \
  --volume safepath_data:/data \
  safepath chown -R 10001:10001 /data
```
