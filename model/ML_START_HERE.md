# Diagnostic update for the ML engineer

137 local tests passed on Python 3.13.2. No new dependencies are required.
The update adds safe failure codes. It does NOT establish or silently fix the
cause of the earlier real-provider failure. Scoring and verbatim checks stay strict.

If the project is already installed:
1. Replace/merge the source files using this archive.
2. Keep your OWN .venv and server environment settings. They are not in the ZIP.
3. Restart the server with your environment's Python:

    .\.venv\Scripts\python.exe -B run.py test
    .\.venv\Scripts\python.exe -B run.py serve

4. If the API budget is agreed, repeat the problematic /v3/evaluate request once.
5. In Swagger, inspect Response headers:

    x-llm-error-code
    x-request-id
    x-llm-provider-status (only for an HTTP error from the provider)

Send those header values and the matching llm_evaluation_failed server-log line.
Do not send API keys, prompts, provider bodies or candidate text for diagnosis.
See docs/ML_DIAGNOSTICS_RU.md for the code meanings.
The old generic JSON detail is intentionally preserved for API compatibility.

For a fresh Windows installation, first install Python 3.13 alongside other versions:

    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-ml-tested.txt
    .\.venv\Scripts\python.exe -B run.py check
    .\.venv\Scripts\python.exe -B run.py test
    .\.venv\Scripts\python.exe -B run.py serve

Swagger: http://127.0.0.1:8000/docs
Python 3.15 has not been validated for this project.
The app reads process environment variables and does not automatically load .env.
Set the Hubris URL, model and key locally. Only a blank template is included.

check/test/cards/mock and catalog/session-start endpoints do not call GPT.
Evaluation, session answers and live-* commands use the provider when configured.

Read docs/REGISTRY_V3_RU.md and docs/ML_HANDOFF_V3.md for the project structure.
Legacy files remain for compatibility. This is still an internal demo without
authentication or durable session storage.
