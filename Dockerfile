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

# Command to run the Streamlit dashboard
CMD streamlit run dashboard/app.py --server.port=${PORT} --server.address=0.0.0.0
