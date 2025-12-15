FROM python:3.14-alpine

WORKDIR /app

# No dependencies needed for basic http.server, 
# but we set unbuffered to see logs immediately in Docker.
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV TEMPLATE_DIR=/app/templates

COPY server.py .
COPY templates ./templates

CMD ["python", "server.py"]
