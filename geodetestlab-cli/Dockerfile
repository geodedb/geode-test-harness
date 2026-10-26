# Multi-stage build for geodetestlab with Geode support
FROM python:3.15-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip==24.3.1 && \
    pip install --no-cache-dir -e .

# Final runtime image
FROM python:3.15-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python environment from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash geodetest
USER geodetest

# Verify the geodetestlab package is importable
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import geodetestlab" || exit 1

# Default command
ENTRYPOINT ["geodetestlab"]
CMD ["--help"]
