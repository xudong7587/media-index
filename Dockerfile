FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
COPY frontend/public ./public
RUN npm install --global pnpm@11.7.0 \
    && pnpm install --frozen-lockfile \
    && pnpm run build

FROM python:3.13-slim@sha256:7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f

WORKDIR /app

ENV PYTHONPATH=/app/backend
ENV STATIC_DIR=/app/frontend
ENV DB_PATH=/app/data/media_index.db

COPY requirements.txt requirements.lock ./
RUN apt-get update \
    && apt-get install --no-install-recommends --yes fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.lock

COPY backend ./backend
COPY VERSION ./VERSION
COPY --from=frontend /src/frontend/dist ./frontend
COPY docker-entrypoint.sh /usr/local/bin/media-index-entrypoint

RUN groupadd --gid 10001 mediaindex \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mediaindex \
    && sed -i 's/\r$//' /usr/local/bin/media-index-entrypoint \
    && chmod 0755 /usr/local/bin/media-index-entrypoint \
    && chmod -R a+rX /app/backend /app/frontend \
    && mkdir -p /app/data \
    && chown -R mediaindex:mediaindex /app

EXPOSE 8000 8097

ENTRYPOINT ["media-index-entrypoint"]
CMD ["python", "-m", "app.combined_server"]
