import os
import time
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("assignment-backend")

app = FastAPI(title="Assignment Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            logger.info("Database initialized successfully")
            return
        except Exception as exc:
            logger.warning(f"DB init attempt {attempt}/{retries} failed: {exc}")
            time.sleep(delay)
    logger.error("Could not initialize database after retries")


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
