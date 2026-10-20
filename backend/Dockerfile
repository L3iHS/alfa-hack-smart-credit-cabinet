FROM python:3.12.10-slim
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
EXPOSE 8000
