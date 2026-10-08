FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" "pyyaml>=6" "jinja2>=3" "pydantic>=2"
COPY . .
ENV PORT=8080 VAR_DIR=/tmp/var INCIDENTS_DIR=/tmp/incidents PYTHONPATH=/app
CMD ["sh", "-c", "uvicorn checkout_svc.main:app --host 0.0.0.0 --port ${PORT}"]
