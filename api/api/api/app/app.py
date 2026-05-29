##"""FastAPI application — REST API + serves the React build as static files."""
##from __future__ import annotations
##
##import os
##from pathlib import Path
##
##from fastapi import FastAPI
##from fastapi.middleware.cors import CORSMiddleware
##from fastapi.staticfiles import StaticFiles
##from fastapi.responses import FileResponse
##
##from .routes import models_router, chat_router
##
##app = FastAPI(title="LLM Console API", version="1.0.0")
##
##app.add_middleware(
##    CORSMiddleware,
##    allow_origins=["*"],
##    allow_methods=["*"],
##    allow_headers=["*"],
##)
##
##app.include_router(models_router, prefix="/api")
##app.include_router(chat_router, prefix="/api")
##
##
##@app.get("/api/health")
##def health() -> dict:
##    return {"ok": True}
##
##
### Serve the React build (produced by `npm run build` inside ui/).
### When running `uvicorn abstract_hugpy.server.app:app` from the repo root,
### this resolves to <repo>/ui/dist.
##_UI_DIST = Path(__file__).parent.parent.parent.parent / "ui" / "dist"
##
##if _UI_DIST.exists():
##    # Mount assets at /assets so Vite's hashed filenames work
##    _assets = _UI_DIST / "assets"
##    if _assets.exists():
##        app.mount("/assets", StaticFiles(directory=_assets), name="assets")
##
##    @app.get("/{full_path:path}", include_in_schema=False)
##    async def spa_fallback(full_path: str):
##        index = _UI_DIST / "index.html"
##        return FileResponse(index)
##
##
##def run() -> None:
##    import uvicorn
##    host = os.getenv("HOST", "0.0.0.0")
##    port = int(os.getenv("PORT", "8000"))
##    uvicorn.run("abstract_hugpy.server.app:app", host=host, port=port, reload=False)
