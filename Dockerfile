# Dockerfile for FindAGraveHelper — issue #93.
#
# Build:
#   docker build -t findagravehelper .
#
# Run the default pytest suite (integration tests excluded, per
# pytest.ini addopts):
#   docker run --rm findagravehelper pytest
#
# Run the diag + integration tests against the bundled Chromium
# (sandbox mode — no live FaG; tests self-skip on missing fixtures):
#   docker run --rm findagravehelper pytest -m "diag or integration" -v
#
# Run with a custom operator ground-truth CSV mounted:
#   docker run --rm -v /host/path/to/ground_truth.csv:/tmp/ground_truth.csv:ro \
#     findagravehelper pytest tests/test_e2e_ground_truth.py -v

FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

LABEL org.opencontainers.image.source="https://github.com/valueforvalue/FindAGraveHelper"
LABEL org.opencontainers.image.description="FindAGraveHelper CI sandbox (issue #93)"
LABEL org.opencontainers.image.licenses="MIT"

# Don't write .pyc files; flush stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy the lock-step CI requirements first (Docker layer cache).
COPY requirements-ci.txt /app/requirements-ci.txt

# Install Python deps. The base image already has Playwright +
# Chromium pre-baked; we only need the Python bindings.
RUN pip install -r /app/requirements-ci.txt

# Copy the project source. .dockerignore keeps fixtures, .git,
# output/, data/, etc. out of the image.
COPY . /app

# Default command: run the default pytest suite. Override with
# `docker run ... <other-command>` for ad-hoc work.
CMD ["pytest"]