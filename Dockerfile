# syntax=docker/dockerfile:1

# ---- builder: resolves deps with uv (wheels only on amd64/arm64; build-essential
# stays as a safety net for any transitive dependency without a prebuilt wheel) ----
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Cacheable layer: install dependencies before copying the source code.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev

# ---- runtime: final image without the compilation toolchain ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libssl3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 cocorreo

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
