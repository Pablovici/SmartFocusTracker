# middleware/Dockerfile
# Builds the Flask middleware container for Google Cloud Run.
# Assigned to: Pablo

# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements first — Docker caches this layer if unchanged
# This avoids reinstalling dependencies on every code change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all middleware source files
COPY . .

# Cloud Run requires the container to listen on PORT env variable
# Gunicorn is used instead of Flask dev server for production stability
# 2 workers is sufficient for Cloud Run single-instance deployment
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app
