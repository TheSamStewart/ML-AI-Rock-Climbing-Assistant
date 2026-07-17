FROM python:3.14-slim

# uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Keep the venv outside /app so a bind-mounted source dir can't shadow it
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install dependencies from the lockfile first so this layer caches
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .

EXPOSE 8000

#This configures uvicorn to listen to all traffic, so that Docker can route traffic to it.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
