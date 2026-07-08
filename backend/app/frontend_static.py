"""
Serve il frontend React buildato dal backend FastAPI.

Serve SOLO alle build desktop (dove non c'è nginx/Vite): la logica si attiva
unicamente se una cartella `dist` del frontend è presente. In Docker/dev il
frontend lo serve nginx o Vite e questa cartella non esiste lato backend → il
mount non si attiva e il comportamento resta invariato.

Percorso della build, in ordine:
  1. env `FRONTEND_DIST` (override esplicito)
  2. bundle PyInstaller: `<_MEIPASS>/frontend` (dati impacchettati)
  3. dev: `<repo>/frontend/dist` se è stato buildato (comodità, opzionale)

Gestisce il routing SPA: qualsiasi path non-API e non-file ricade su
`index.html`, così i deep-link di react-router (es. /performance) funzionano.
"""
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def _frontend_dist() -> Path | None:
    env = os.getenv("FRONTEND_DIST")
    if env:
        p = Path(env)
        return p if p.is_dir() else None

    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS", ".")) / "frontend"
        return p if p.is_dir() else None

    # Dev: se il frontend è stato buildato (repo/frontend/dist). In Docker questa
    # cartella non è nel container backend → None.
    p = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return p if p.is_dir() else None


def mount_frontend(app: FastAPI) -> bool:
    """Monta il frontend statico se disponibile. Ritorna True se montato."""
    dist = _frontend_dist()
    if dist is None:
        return False

    index = dist / "index.html"
    if not index.is_file():
        logger.warning(f"Frontend dist trovato ma senza index.html: {dist}")
        return False

    # Asset con hash generati da Vite.
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    # Catch-all SPA: registrato per ultimo, così le route /api/* esplicite vincono.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Non intercettare le API: un path /api/* sconosciuto deve dare 404 JSON,
        # non l'index.html.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))

    logger.info(f"Frontend statico servito da {dist}")
    return True
