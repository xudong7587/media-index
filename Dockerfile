FROM node:24-alpine AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
RUN npm install && npm run build

FROM python:3.13-slim

WORKDIR /app

ENV PYTHONPATH=/app/backend
ENV STATIC_DIR=/app/frontend
ENV DB_PATH=/app/data/media_index.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY matching.py ./backend/matching.py
COPY --from=frontend /src/frontend/dist ./frontend

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
