# chf.tech

ИИ-платформа для проведения технических собеседований в финтехе.

## Запуск через Docker

Из корня репозитория выполните:

```bash
docker build -t chf-tech .
```

Запустите контейнер, передав ключ LLM:

```bash
docker run --rm \
  --name chf-tech \
  -p 5173:5173 \
  -p 8081:8081 \
  -e LLM_API_KEY="ваш-llm-ключ" \
  chf-tech
```

Откройте приложение:

```text
http://localhost:5173
```

Проверить backend:

```text
http://localhost:8081/health
```

При необходимости можно переопределить модель и сервис, предоставляющий модель:

```bash
docker run --rm \
  -p 5173:5173 \
  -p 8081:8081 \
  -e LLM_API_KEY="ваш-llm-ключ" \
  -e LLM_BASE_URL="https://api.openai.com/v1" \
  -e LLM_MODEL="gpt-4o-mini" \
  chf-tech
```

Остановить контейнер: `Ctrl+C`.

## Запуск через NixOS

В корне репозитория выполните:

```bash
export LLM_API_KEY="ваш-llm-ключ"
nix run .#all
```

Или запустите компоненты отдельно:

```bash
export LLM_API_KEY="ваш-llm-ключ"

nix run .#backend
nix run .#frontend
```

Приложение будет доступно по адресу:

```text
http://127.0.0.1:5173
```

Backend:

```text
http://127.0.0.1:8081/health
```

