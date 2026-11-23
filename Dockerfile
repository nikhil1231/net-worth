# Dashboard + scheduler on one port. Needs DATABASE_URL (Postgres); mount accounts.yaml, an env file and /app/data (cookies, OAuth tokens).
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY networth/ networth/
COPY --from=frontend /networth/web/static/ networth/web/static/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["python", "-m", "networth"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
