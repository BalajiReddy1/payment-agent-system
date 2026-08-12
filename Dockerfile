# Python base image
FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Cloud Run sets the PORT environment variable (usually 8080)
ENV PORT=8080
EXPOSE 8080

# Run the operations console. It binds 0.0.0.0 itself and is built on
# http.server from the standard library, so the image serves the UI even if
# every optional dependency above failed to install.
CMD ["sh", "-c", "python web/server.py ${PORT}"]
