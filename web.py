import asyncio
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import WEB_PORT
from db import init_db, get_pool
from api_auth import router as auth_router
from api_chat import router as chat_router
from api_admin import router as admin_router
from tools.populate_stocknames import populate_stocknames

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

STOCKNAMES_REFRESH_TIME = dtime(19, 0)  # 19:00 local time, after market close


async def _stocknames_scheduler():
    """On startup: populate if empty. Then refresh daily at 19:00."""
    pool = await get_pool()

    count = await pool.fetchval("SELECT COUNT(*) FROM stocknames")
    if count == 0:
        logger.info("stocknames table is empty — running initial populate...")
        try:
            await populate_stocknames(pool)
        except Exception as e:
            logger.error(f"Initial stocknames populate failed: {e}")

    while True:
        now = datetime.now()
        next_run = datetime.combine(now.date(), STOCKNAMES_REFRESH_TIME)
        if next_run <= now:
            next_run += timedelta(days=1)
        sleep_secs = (next_run - now).total_seconds()
        logger.info(f"stocknames next refresh in {sleep_secs/3600:.1f}h (at {next_run.strftime('%H:%M')})")
        await asyncio.sleep(sleep_secs)

        logger.info("Running daily stocknames refresh...")
        try:
            await populate_stocknames(pool)
        except Exception as e:
            logger.error(f"Daily stocknames refresh failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized for web server")
    asyncio.create_task(_stocknames_scheduler())
    yield


app = FastAPI(title="Financial Research Agent", lifespan=lifespan)

# CORS for dev (Vite runs on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)

# Ensure output directory exists (files served via authenticated /api/chat/files/ endpoint)
os.makedirs(os.path.join(os.path.dirname(__file__), "output"), exist_ok=True)

# In production, serve the built React frontend
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    from fastapi.responses import FileResponse as _FileResponse

    # Serve /assets/* and other real files directly; fall back to index.html for
    # all unmatched paths so React Router can handle client-side routes like /share/...
    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str = ""):
        candidate = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return _FileResponse(candidate)
        return _FileResponse(os.path.join(frontend_dist, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web:app", host="0.0.0.0", port=WEB_PORT, reload=True)
