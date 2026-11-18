FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    SAFEPATH_CACHE_DIR=/data/cache \
    SAFEPATH_DATABASE_PATH=/data/db.sqlite3 \
    SAFEPATH_RUN_MIGRATIONS=false

WORKDIR /app

RUN groupadd --system --gid 10001 safepath \
    && useradd --system --uid 10001 --gid safepath --home-dir /app --no-create-home safepath \
    && mkdir -p /data \
    && chown safepath:safepath /data

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=safepath:safepath manage.py gunicorn.conf.py ./
COPY --chown=safepath:safepath Model /app/Model
COPY --chown=safepath:safepath web /app/web
COPY --chown=safepath:safepath safepath_backend /app/safepath_backend
COPY --chown=safepath:safepath data /app/data
COPY --chown=safepath:safepath docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --chown=safepath:safepath scripts/healthcheck.py /app/scripts/healthcheck.py

RUN chmod 755 /app/docker/entrypoint.sh \
    && DJANGO_DEBUG=False \
       DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
       DJANGO_ALLOWED_HOSTS=localhost \
       SAFEPATH_CARTO_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
       python manage.py collectstatic --noinput --ignore "web/css/src/*" \
    && mkdir -p /data/cache \
    && chown safepath:safepath /data/cache \
    && chmod 700 /data/cache

USER safepath
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python /app/scripts/healthcheck.py

CMD ["/app/docker/entrypoint.sh"]
