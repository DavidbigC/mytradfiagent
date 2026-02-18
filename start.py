"""Single entry point to run the app — web server."""

import asyncio
import logging
import os
import subprocess

import uvicorn
from config import WEB_PORT
from db import init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _build_frontend_if_needed():
    """Build the React frontend if dist/ is missing or stale."""
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")
    src_dir = os.path.join(frontend_dir, "src")
    node_modules = os.path.join(frontend_dir, "node_modules")

    if not os.path.isdir(frontend_dir):
        logger.warning("frontend/ directory not found, skipping build")
        return

    # Install deps if needed
    if not os.path.isdir(node_modules):
        logger.info("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)

    # Build if dist/ doesn't exist or src/ is newer
    need_build = not os.path.isdir(dist_dir)
    if not need_build:
        dist_mtime = os.path.getmtime(dist_dir)
        for root, _, files in os.walk(src_dir):
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > dist_mtime:
                    need_build = True
                    break
            if need_build:
                break

    if need_build:
        logger.info("Building frontend...")
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)
        logger.info("Frontend build complete")
    else:
        logger.info("Frontend dist/ is up to date")


async def main():
    await init_db()
    logger.info("Database initialized")

    from web import app

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=WEB_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info(f"Web UI: http://localhost:{WEB_PORT}")
    await server.serve()


if __name__ == "__main__":
    _build_frontend_if_needed()
    asyncio.run(main())
