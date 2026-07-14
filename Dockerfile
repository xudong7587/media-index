FROM node:24-alpine AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
COPY frontend/public ./public
RUN npm install --global pnpm@11.7.0 \
    && pnpm install --frozen-lockfile \
    && pnpm run build

FROM python:3.13-slim

WORKDIR /app

ENV PYTHONPATH=/app/backend
ENV STATIC_DIR=/app/frontend
ENV DB_PATH=/app/data/media_index.db

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY backend ./backend
COPY VERSION ./VERSION
COPY --from=frontend /src/frontend/dist ./frontend
COPY docker-entrypoint.sh /usr/local/bin/media-index-entrypoint

RUN groupadd --gid 10001 mediaindex \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mediaindex \
    && sed -i 's/\r$//' /usr/local/bin/media-index-entrypoint \
    && chmod 0755 /usr/local/bin/media-index-entrypoint \
    && mkdir -p /app/data \
    && chown -R mediaindex:mediaindex /app

EXPOSE 8000

ENTRYPOINT ["media-index-entrypoint"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
