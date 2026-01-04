import os
from fastapi import FastAPI

app = FastAPI()

SERVICE_NAME = os.getenv("SERVICE_NAME", "agentic-ai")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


@app.get("/")
def root() -> dict:
    return {
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "message": "Service is running",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
