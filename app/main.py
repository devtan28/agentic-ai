import os
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

print("DEBUG ENVIRONMENT =", os.getenv("ENVIRONMENT"))
print("DEBUG SERVICE_NAME =", os.getenv("SERVICE_NAME"))

app = FastAPI()

SERVICE_NAME = os.getenv("SERVICE_NAME")
ENVIRONMENT = os.getenv("ENVIRONMENT")

if not SERVICE_NAME:
    raise RuntimeError("SERVICE_NAME is required")

if ENVIRONMENT not in {"development", "staging", "production"}:
    raise RuntimeError("ENVIRONMENT must be development, staging, or production")


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
