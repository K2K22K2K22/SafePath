# Use official Python
FROM python:3.13-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt update && apt install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose port 8000 for Django server
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=3)"

# Default command (development)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--insecure"]
