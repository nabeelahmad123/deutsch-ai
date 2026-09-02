# Shared image for the backend API and both MCP servers.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
RUN pip install --upgrade pip && pip install ".[agent]"

EXPOSE 8000 8100 8101

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
