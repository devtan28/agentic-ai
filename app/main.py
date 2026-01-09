import os, logging, json, random, time, copy, uuid
from datetime import datetime
from fastapi import Request
from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi import HTTPException, Header
from fastapi.responses import JSONResponse
from app.errors import ClientError, OperationalError
from typing import TypedDict
from threading import Lock
from collections import defaultdict, deque

idempotency_lock = Lock()
IDEMPOTENCY_TTL_SECONDS = 60 * 60

WINDOWS_SECONDS = 30

HEALTH_STATE = {
    "status": "healthy",
    "since": time.time(),
}

metrics = {
    "requests": deque(),
    "errors": deque(),
    "retries": deque(),
    "latencies": deque(),
    "requests_total": 0,
    "errors_total": 0,
    "retries_total": 0,
    "latency_ms": [],
}

HEALTH_THRESHOLDS = {
    "error_unhealthy": 0.05,

    "retry_degraded_enter": 0.2,
    "retry_degraded_exit": 0.05,

    "min_state_duration": 10, # seconds
}

CIRCUIT_STATE = {
    "state": "CLOSED", # CLOSED | OPEN | HALF_OPEN
    "opened_at": None,
}

CIRCUIT_OPEN_TIMEOUT = 30 # seconds

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        #include structured context if present
        for field in {
            "request_id",
            "idempotency_key",
            "item_id",
            "path",
            "status_code",
        }:
            if hasattr(record, field):
                log_record[field] = getattr(record, field)

        return json.dumps(log_record)

class IdempotencyRecord(TypedDict):
    response: dict
    created_at: float

idempotency_store: dict[str, IdempotencyRecord] = {}

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

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("agentic-ai")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False

app = FastAPI()

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    start_time = time.time()

    request_id = str(uuid.uuid4())
    # attach to request state
    request.state.request_id = request_id

    metrics["requests_total"] += 1
    now = time.time()
    metrics["requests"].append(now)

    logger.info(
        "Request started",
        extra={"request_id": request_id, "path": request.url.path},
    )
    try:
        response = await call_next(request)
        return response
    except Exception:
        metrics["errors_total"] += 1
        metrics["errors"].append(time.time())
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        metrics["latency_ms"].append(duration_ms)
        metrics["latencies"].append((time.time(), duration_ms))

        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "duration_ms": round(duration_ms, 2),
            },
        )

@app.middleware("http")
async def circuit_breaker_guard(request: Request, call_next):
    # Allow control-plane endpoints always
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    state = evaluate_cricuit()

    if state == "OPEN":
        return JSONResponse(
            status_code = 503,
            content={"detail": "Service temporarily unavailable"},
        )
    return await call_next(request)

def evaluate_health():
    prune_old_events()

    now = time.time()
    current = HEALTH_STATE["status"]
    since = HEALTH_STATE["since"]

    req = len(metrics["requests"])
    if req == 0:
        return HEALTH_STATE
    
    error_rate = len(metrics["errors"]) / req
    retry_rate = len(metrics["retries"]) / req

    # UNHEALTHY dominates
    if error_rate > HEALTH_THRESHOLDS["error_unhealthy"]:
        return set_health("unhealthy", now, "error rate too high")
    
    # DEGRADED transitions
    if current == "healthy":
        if retry_rate > HEALTH_THRESHOLDS["retry_degraded_enter"]:
            return set_health("degraded", now, "retry rate high")
    
    if current == "degraded":
        if (
            retry_rate < HEALTH_THRESHOLDS["retry_degraded_exit"]
            and now - since > HEALTH_THRESHOLDS["min_state_duration"]
        ):
            return set_health("healthy", now, "recovered")
        
    return HEALTH_STATE

def cleanup_idempotency_store():
    now = time.time()
    expired_keys = [
        key 
        for key, record in idempotency_store.items()
        if now - record["created at"] > IDEMPOTENCY_TTL_SECONDS
    ]

    for key in expired_keys:
        del idempotency_store[key]

@app.post("/create-item")
def create_item(
    request: Request,
    name: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code = 400,
            detail="Idempotency_Key header is required",
        )
    with idempotency_lock:
        record = idempotency_store.get(idempotency_key)

    if record:
        return copy.deepcopy(record["response"])
    
    #Simulation creation
    item = {"id": len(idempotency_store) + 1, "name":name}
    response = {"item":item}

    idempotency_store[idempotency_key] = {
        "response": copy.deepcopy(response),
        "created at": time.time()
    }

    logger.info(
        "item created",
        extra={
            "request_id": request.state.request_id,
            "idempotency_key": idempotency_key, 
            "item_id": item["id"],
            },
    )

    return response

def unreliable_service() -> str:
    if random.random() < 0.5:
        raise OperationalError("Temporary upsteream error")
    return "success"

def call_with_retry(fn, retries: int = 3, delay: float = 0.5):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except OperationalError as exc:
            last_exc = exc
            metrics["retries_total"] += 1
            metrics["retries"].append(time.time())
            logger.warning(
                "Retryable failure",
                extra={"attempt": attempt, "error": str(exc)}
            )
        if attempt == retries:
            raise last_exc
        time.sleep(delay * attempt)
    logger.warning("Retries exhausted - returning fallback")
    return "fallback"

@app.get("/unstable")
def unstable():
    result = call_with_retry(unreliable_service)
    return {"result": result}

@app.get("/metrics")
def get_metrics():
    avg_latency = (
        sum(metrics["latency_ms"]) / len(metrics["latency_ms"])
        if metrics["latency_ms"]
        else 0
    )

    return {
        "request_total": metrics["requests_total"],
        "errors_total": metrics["errors_total"],
        "retries_total": metrics["retries_total"],
        "avg_latency_ms": round(avg_latency, 2),
    }

@app.get("/health")
def health():
    health_state = evaluate_health()

    logger.info(
        "Health evaluated",
        extra={
            "status": health_state["status"],
            "reason": health_state.get("reason")
        },
    )

    return health_state

def evaluate_cricuit():
    health = evaluate_health()
    now = time.time()

    if health["status"] == "unhealthy":
        if CIRCUIT_STATE["state"] != "OPEN":
            CIRCUIT_STATE["state"] = "OPEN"
            CIRCUIT_STATE["opened_at"] = now
        return CIRCUIT_STATE["state"]
    
    if CIRCUIT_STATE["state"] == "OPEN":
        if now - CIRCUIT_STATE["opened_at"] > CIRCUIT_OPEN_TIMEOUT:
            CIRCUIT_STATE["state"] = "HALF_OPEN"
        return CIRCUIT_STATE["state"]
    
    if health["status"] == "degraded":
        CIRCUIT_STATE["state"] = "HALF_OPEN"
        return CIRCUIT_STATE["state"]
    
    CIRCUIT_STATE["state"] = "CLOSED"
    return CIRCUIT_STATE["state"]

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
def root():
    health = evaluate_health()

    if health["status"] == "degraded":
        return {
            "status": "degraded",
            "message": "Serving fallback response",
            "data": {
                "service": SERVICE_NAME,
                "mode": "fallback",
            },
        }

    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "message": "Service is running",
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

def set_health(status: str, now: float, reason: str):
    HEALTH_STATE["status"] = status
    HEALTH_STATE["since"] = now
    HEALTH_STATE["reason"] = reason

    logger.info(
        "Health state transition",
        extra={"status": status, "reason": reason}
    )
    return HEALTH_STATE

def prune_old_events():

    cutoff = time.time() - WINDOWS_SECONDS

    for key in ["requests", "errors", "retries"]:
        while metrics[key] and metrics[key][0] < cutoff:
            metrics[key].popleft()

    while metrics["latencies"] and metrics["latencies"][0][0] < cutoff:
        metrics["latencies"].popleft()