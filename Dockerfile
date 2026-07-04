# syntax=docker/dockerfile:1

# ---- builder: resolves deps with uv (all dependencies ship prebuilt
# manylinux wheels for amd64/arm64, no compiler needed) ----
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Cacheable layer: install dependencies before copying the source code.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 cocorreo

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY pyproject.toml README.md ./

ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p /data && chown cocorreo:cocorreo /data
USER cocorreo
VOLUME ["/data"]

EXPOSE 8000
ENTRYPOINT ["cocorreo"]
CMD ["serve", "--data-dir", "/data", "--host", "0.0.0.0", "--port", "8000"]
