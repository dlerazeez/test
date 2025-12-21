from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routers.assets import router as assets_router
from app.routers.coa import router as coa_router
from app.routers.expenses import router as expenses_router
from app.routers.pending_expenses import router as pending_expenses_router
from app.routers.vendors import router as vendors_router


def create_app() -> FastAPI:
    app = FastAPI(title="Assets & Expenses Service")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root directory: .../app/factory.py -> root is two levels up
    root_dir = Path(__file__).resolve().parents[1]
    frontend_dir = (root_dir / "frontend").resolve()

    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_frontend():
        return (frontend_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health():
        return {"ok": True}

    # Routers
    app.include_router(coa_router)
    app.include_router(vendors_router)
    app.include_router(assets_router)
    app.include_router(expenses_router)
    app.include_router(pending_expenses_router)

    return app
