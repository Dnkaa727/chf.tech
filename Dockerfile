FROM node:22-bookworm-slim AS frontend-build

WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ARG VITE_BACKEND_URL=http://localhost:8081
ENV VITE_BACKEND_URL=${VITE_BACKEND_URL}
RUN npx vite build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_BASE_URL=https://api.hubris.pw/v1 \
    LLM_MODEL=openai/gpt-4o-mini \
    LLM_TIMEOUT_SECONDS=75 \
    LLM_PIPELINE_MODE=one_stage \
    LLM_JSON_MODE=schema \
    LLM_MESSAGE_MODE=system_user \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8081 \
    FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

WORKDIR /app

COPY model/requirements.txt /tmp/model-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/model-requirements.txt \
      'uvicorn[standard]>=0.30,<1.0' \
      'httpx>=0.27,<1.0'

COPY backend ./backend
COPY model ./model
COPY --from=frontend-build /src/frontend/dist ./frontend/dist

EXPOSE 5173 8081

CMD ["sh", "-c", "uvicorn backend.main:app --host \"$BACKEND_HOST\" --port \"$BACKEND_PORT\" & backend_pid=$!; trap 'kill \"$backend_pid\" 2>/dev/null || true' EXIT INT TERM; exec python -m http.server 5173 --bind 0.0.0.0 --directory /app/frontend/dist"]
