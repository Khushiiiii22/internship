FROM python:3.12-slim

LABEL maintainer="NSE Market Data Downloader"
LABEL description="Automated downloader for NSE India market data"

WORKDIR /app

# Install dependencies first (leverages Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data and logs directories
RUN mkdir -p data logs

# Default command: download all datasets
ENTRYPOINT ["python", "main.py"]

# Default arguments (can be overridden)
CMD []
