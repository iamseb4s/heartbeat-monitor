FROM python:3.14-alpine

WORKDIR /app

# Install system dependencies
RUN apk add --no-cache gcc musl-dev linux-headers

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code to /app
COPY backend/ .

# Copy frontend code to /app/frontend so it's baked into the image
COPY frontend/ frontend/

# Expose FastAPI port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]