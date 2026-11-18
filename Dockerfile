FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
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
COPY --chown=safepath:safepath Model web safepath_backend data ./
COPY --chown=safepath:safepath docker/entrypoint.sh /app/docker/entrypoint.sh

RUN chmod 755 /app/docker/entrypoint.sh

USER safepath
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health/', timeout=3)"

CMD ["/app/docker/entrypoint.sh"]
