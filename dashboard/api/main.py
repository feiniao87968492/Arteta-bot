import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from dashboard.api.config import get_settings
from dashboard.api.routers import auth, bot_chat, bot_power, config, docs, groups, logs, memories, overview, prompts, verify
from dashboard.api.schemas import ok


def _mount_frontend(app: FastAPI, web_dist: str) -> None:
    index_path = os.path.join(web_dist, "index.html")
    assets_path = os.path.join(web_dist, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="dashboard-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            return PlainTextResponse("Not Found", status_code=404)
        static_path = os.path.abspath(os.path.join(web_dist, path))
        web_root = os.path.abspath(web_dist)
        if static_path.startswith(web_root + os.sep) and os.path.isfile(static_path):
            return FileResponse(static_path)
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return PlainTextResponse("Dashboard frontend build not found. Run npm --prefix dashboard/web run build.", status_code=503)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Arteta Developer Mission Control")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(bot_chat.router)
    app.include_router(bot_power.router)
    app.include_router(groups.router)
    app.include_router(docs.router)
    app.include_router(config.router)
    app.include_router(logs.router)
    app.include_router(memories.router)
    app.include_router(prompts.router)
    app.include_router(overview.router)
    app.include_router(verify.router)

    @app.get("/api/health")
    def health():
        return ok({"status": "healthy", "readonly": settings.readonly})

    _mount_frontend(app, settings.web_dist)
    return app


app = create_app()
