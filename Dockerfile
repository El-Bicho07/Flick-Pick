# Standard production Dockerfile for FlickPick
FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Set work directory
WORKDIR /app

# Install essential system dependencies and certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Collect static assets into staticfiles for WhiteNoise
RUN python manage.py collectstatic --noinput

# Expose the default port
EXPOSE 8000

# Start Gunicorn binding to $PORT (assigned dynamically by Render, Railway, Cloud Run)
# Defaults to 1 worker for Render Free Tier (512MB RAM) to prevent ONNX/FastEmbed memory exhaustion;
# can be overridden by setting WEB_CONCURRENCY environment variable.
CMD ["sh", "-c", "exec gunicorn flickpick.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --timeout 120 --access-logfile - --error-logfile -"]
