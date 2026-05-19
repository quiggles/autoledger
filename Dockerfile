# ──────────────────────────────────────────────────────────────────────────────
# AutoLedger Dockerfile
# Builds a lightweight production image using Gunicorn as the WSGI server.
# Data is stored on a mounted volume so it persists across container restarts.
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies first (separate layer = better Docker cache reuse)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Declare the data volume — Docker (and Compose) will mount this externally
VOLUME ["/data"]

# Expose the application port
EXPOSE 5000

# Run Gunicorn with a single sync worker.
# We use 1 worker intentionally — the JSON file storage backend has no
# transaction support, so concurrent writes from multiple workers could
# corrupt data. A single worker serialises all requests safely.
# At single-user home-lab scale, 1 worker is more than sufficient.
CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:5000", "app:app"]
