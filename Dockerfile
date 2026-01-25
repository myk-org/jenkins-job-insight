# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install git (needed for gitpython dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ src/

# Create venv and install dependencies
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install git (required at runtime for gitpython), curl (for Claude CLI), and nodejs/npm (for Gemini CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy project files needed by uv
COPY --from=builder /app/pyproject.toml /app/uv.lock ./

# Copy source code
COPY --from=builder /app/src /app/src

# Copy uv for runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create data directory for SQLite persistence
RUN mkdir -p /data && chown appuser:appuser /data

# Fix ownership for appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Install Claude Code CLI (installs to ~/.local/bin)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Install Cursor Agent CLI (installs to ~/.local/bin)
RUN curl -fsSL https://cursor.com/install | bash

# Configure npm for non-root global installs and install Gemini CLI
RUN mkdir -p /home/appuser/.npm-global \
    && npm config set prefix '/home/appuser/.npm-global' \
    && npm install -g @google/gemini-cli

# Ensure CLIs are in PATH
ENV PATH="/home/appuser/.local/bin:/home/appuser/.npm-global/bin:${PATH}"

EXPOSE 8000

# Use uv run for uvicorn
ENTRYPOINT ["uv", "run", "uvicorn", "jenkins_job_insight.main:app", "--host", "0.0.0.0", "--port", "8000"]
