# Backend Dockerfile — local development (used by docker-compose)
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (gcc needed for building Python packages)
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy package definition first for better layer caching
COPY pyproject.toml ./
COPY src ./src

# Install all dependencies including dev tools
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

