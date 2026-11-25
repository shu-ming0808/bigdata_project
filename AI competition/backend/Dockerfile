FROM node:24-bookworm-slim AS codex
RUN npm install --global @openai/codex@0.160.0 && codex --version

FROM python:3.13-slim-bookworm
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && codex --version
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app.py backend/case.json ./backend/
RUN useradd --create-home --uid 10001 demo && install -d -o demo -g demo /home/demo/.codex
USER demo
ENV CODEX_HOME=/home/demo/.codex
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
