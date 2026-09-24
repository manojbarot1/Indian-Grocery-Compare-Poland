from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .db import SessionLocal, init_db
from .ingest.registry import load_shops

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as session:
        load_shops(session)
    yield


app = FastAPI(
    title="DesiPrice API",
    version="0.1.0",
    description=(
        "Price comparison for Indian groceries in Poland. Shows every shop's "
        "price for the same product, and finds the cheapest way to split a "
        "shopping list across shops."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    """Zero-build UI, so the stack is usable without installing Node."""
    return FileResponse(STATIC_DIR / "index.html")
