import os
import time
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

# Structured JSON logs to stdout. Promtail (DaemonSet on each node) tails
# container stdout and ships it to Loki - this format is what makes those
# logs actually filterable/queryable in Grafana/LogQL instead of being
# opaque text blobs.
log_handler = logging.StreamHandler()
log_handler.setFormatter(
    jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
)
logger = logging.getLogger("assignment-backend")
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)
logger.propagate = False

app = FastAPI(title="Assignment Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Emits one structured log line per request: method, path, status,
    latency, and pod hostname. This is the log line you'll grep/LogQL-query
    during the failure-simulation section to correlate a failing request
    with the OOMKill event in kubectl describe."""
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        "request_handled",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "pod": os.getenv("HOSTNAME", "unknown"),
        },
    )
    return response


# Exposes /metrics in Prometheus exposition format: request count, latency
# histograms, and in-flight requests, all labeled by path/method/status.
# Prometheus Operator's ServiceMonitor (k8s/09-servicemonitor.yaml) scrapes
# this on a schedule; nothing here pushes metrics anywhere.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "assignmentdb")
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

READY = {"db": False}


class Item(BaseModel):
    name: str
    description: str = ""


@contextmanager
def get_conn():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=3,
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db(retries: int = 5, delay: int = 2):
    for attempt in range(1, retries + 1):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS items (
                            id SERIAL PRIMARY KEY,
                            name TEXT NOT NULL,
                            description TEXT,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                        """
                    )
                    conn.commit()
            READY["db"] = True
            logger.info("db_init_success", extra={"attempt": attempt})
            return
        except Exception as exc:
            logger.warning(
                "db_init_attempt_failed",
                extra={"attempt": attempt, "retries": retries, "error": str(exc)},
            )
            time.sleep(delay)
    logger.error("db_init_exhausted_retries", extra={"retries": retries})


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    """Liveness: is the process itself alive. Deliberately does NOT touch the DB
    so a slow/down DB doesn't get the container killed for the wrong reason."""
    return {"status": "alive"}


@app.get("/ready")
def ready():
    """Readiness: is this pod actually able to serve real traffic (DB reachable)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ready", "db": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"not ready: {exc}")


@app.get("/api/items")
def list_items():
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, name, description, created_at FROM items ORDER BY id DESC")
                return cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}")


@app.post("/api/items")
def create_item(item: Item):
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO items (name, description) VALUES (%s, %s) RETURNING id, name, description, created_at",
                    (item.name, item.description),
                )
                row = cur.fetchone()
                conn.commit()
                return row
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}")


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
                conn.commit()
                return {"deleted": item_id}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}")


@app.get("/api/info")
def info():
    """Handy during the video: shows which pod served the request."""
    return {
        "hostname": os.getenv("HOSTNAME", "unknown"),
        "db_host": DB_HOST,
    }