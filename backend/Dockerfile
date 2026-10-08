FROM python:3.14-slim

# ultralytics pulls in full (non-headless) opencv-python, which links against
# X11/GL shared libraries that don't ship in the slim image - nothing here
# renders a GUI, but cv2 still needs these .so files present to import.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

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

# This configures uvicorn to listen to all traffic, so that Docker can route traffic to it.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
