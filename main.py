"""
NID Barcode Reader — FastAPI application entry point.

Start locally:  python main.py
With uvicorn:   uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.decoders import AVAILABLE_DECODERS
from app.routes import router

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.executor = ThreadPoolExecutor(max_workers=settings.thread_workers)
    logger.info(
        "Started %s v%s (workers=%d, timeout=%ds)",
        settings.app_name,
        settings.app_version,
        settings.thread_workers,
        settings.timeout_seconds,
    )
    logger.info("Available decoders: %s", AVAILABLE_DECODERS)
    if "pyzbar" not in AVAILABLE_DECODERS:
        logger.warning(
            "pyzbar not loaded — install libzbar0 (apt) or zbar (brew) for best performance"
        )
    yield
    app.state.executor.shutdown(wait=True)
    logger.info("Thread pool shut down cleanly")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="High-performance PDF417 barcode scanner for Bangladesh NID cards",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS is intentionally open — this is an internal microservice
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
        workers=1,  # ThreadPoolExecutor handles concurrency; >1 workers multiplies memory
    )
