FROM python:3.13.2-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create directories
RUN mkdir -p data config

# Copy the application code
COPY main.py ./
COPY src/ ./src/

# Create a non-root user to run the application
RUN useradd -m appuser
RUN chown -R appuser:appuser /app
USER appuser

# Set environment variables to Python output
ENV PYTHONUNBUFFERED=1

# Default to bot mode (can be overridden in docker-compose)
CMD ["python", "main.py", "--mode", "bot"]