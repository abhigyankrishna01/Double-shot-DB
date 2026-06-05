FROM python:3.11-slim

WORKDIR /app

# System deps for asyncpg / libpq
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Build context is the project root (see docker-compose.yml)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend package — keeps frontend/, tests/, .env out of the image
COPY backend/ ./backend/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
