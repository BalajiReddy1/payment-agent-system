# Python base image
FROM python:3.11-slim

# Set working directory
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

# Expose ports
# 8501 - Streamlit Dashboard
# 8000 - FastAPI
EXPOSE 8501 8000

# Default command (can be overridden in docker-compose)
CMD ["python", "main.py", "--mode", "demo"]
