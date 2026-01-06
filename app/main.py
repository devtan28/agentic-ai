import os
import logging
import uuid
from fastapi import Request
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from app.errors import ClientError, OperationalError
import random
import time

load_dotenv()

SERVICE_NAME = os.getenv("SERVICE_NAME")
ENVIRONMENT = os.getenv("ENVIRONMENT")

if not SERVICE_NAME:
    raise RuntimeError("SERVICE_NAME is required")

if ENVIRONMENT not in {"development", "staging", "production"}:
    raise RuntimeError("ENVIRONMENT must be development, staging, or production")

LOG_LEVEL = logging.INFO
if ENVIRONMENT == "development":
    LOG_LEVEL = logging.DEBUG
elif ENVIRONMENT == "production":
    LOG_LEVEL = logging.WARNING

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agentic-ai")

app = FastAPI()

def unreliable_service() -> str:
    if random.random() < 0.5:
        raise OperationalError("Temporary upsteream error")
    return "success"

def call_with_retry(fn, retries: int = 3, delay: float = 0.5):
    for attempt in range(1, retries +1):
        try:
            return fn()
        except OperationalError as exc:
            last_exc = exc
            logger.warning(
                "Retryable failure",
                extra={"attempt": attempt, "error": str(exc)}
            )
        if attempt == retries:
            raise last_exc
        time.sleep(delay * attempt)

@app.get("/unstable")
def unstable():
    result = call_with_retry(unreliable_service)
    return {"result": result}

@app.exception_handler(ClientError)
async def client_error_handler(request: Request, exc: ClientError):
    logger.warning(
        "Client error",
        extra={"path": request.url.path, "error": str(exc)},
    )
    return JSONResponse(
        status_code=400,
        content={"error_type": "client_error", "detail": str(exc)},
    )


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    logger.error(
        "Operational error",
        extra={"path": request.url.path, "error": str(exc)},
    )
    return JSONResponse(
        status_code=503,
        content={"error_type": "operational_error", "detail": str(exc)},
    )


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(
        "Request started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )

    response = await call_next(request)

    logger.info(
        "Request finished",
        extra={
            "request_id": request_id,
            "status_code": response.status_code,
        },
    )

    return response

logger.info(
    "Service starting",
    extra={
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
    },
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

@app.get("/square")
def square(n: int):
    #raise OperationalError("database unavailable")

    if n < 0:
        raise ClientError("n must be non-negative")
    return {"n": n, "square": n * n}



@app.get("/")
def root(request: Request) -> dict:
    logger.info(
        "Root endpoint called",
        extra={"request_id": request.state.request_id},
    )
    return {
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "message": "Service is running",
        "request_id": request.state.request_id,
    }



@app.get("/health")
def health(request: Request) -> dict:
    logger.debug(
        "Health check called",
        extra={"request_id": request.state.request_id},
        )
    
    return {
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "message": "Status OK",
        "request_id": request.state.request_id,
        }
