FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "google-cloud-aiplatform[agent_engines]>=1.100" "google-cloud-storage>=2"
COPY main.py proposals.py ./
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
