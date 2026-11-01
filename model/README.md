# chf.tech interview model

This directory contains one canonical technical interview model. It supports the
25-card catalog, explainable card selection, in-memory interview sessions, strict
evidence validation, red-flag detection, and the two-stage OpenAI-compatible LLM
evaluation pipeline.

Run locally:

```bash
uvicorn api:app --app-dir model --reload
```

The model API exposes `/cards`, `/cards/select`, `/prepare`, `/evaluate`,
`/session/start`, `/session/answer`, and `/session/{session_id}`. The backend
gateway uses the same model package directly and keeps its existing conference
and WebSocket contract.
