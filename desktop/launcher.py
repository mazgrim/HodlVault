"""
Launcher dell'app desktop HodlVault (single-user, senza browser).

Avvia il backend FastAPI su una porta locale libera in un thread, aspetta che
risponda, poi apre una finestra nativa (pywebview) sull'app. Alla chiusura della
finestra ferma il server ed esce.

Ambiente impostato PRIMA di importare l'app:
  • DESKTOP_MODE=1  → login passwordless single-user
  • SECRET_KEY      → generato una volta e persistito nella cartella dati, così i
    token restano validi fra un riavvio e l'altro.
  • FRONTEND_DIST   → in dev punta a frontend/dist; nel bundle PyInstaller il
    frontend è in _MEIPASS/frontend e lo risolve frontend_static.

Usato sia come entry-point del binario PyInstaller sia lanciabile in dev:
    python desktop/launcher.py
"""
import os
import sys
import socket
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "HodlVault"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bootstrap_paths() -> None:
    """Rende importabile il package `app` (backend) sia in dev che nel bundle."""
    if _is_frozen():
        return  # i moduli sono già nel bundle
    here = Path(__file__).resolve().parent
    backend = here.parent / "backend"
    if backend.is_dir():
        sys.path.insert(0, str(backend))
    # In dev, se il frontend è stato buildato, servilo dal backend.
    dist = here.parent / "frontend" / "dist"
    if dist.is_dir() and not os.getenv("FRONTEND_DIST"):
        os.environ["FRONTEND_DIST"] = str(dist)


def _load_or_create_secret() -> str:
    """SECRET_KEY stabile fra i riavvii, salvato nella cartella dati."""
    from app.data_dir import get_data_dir  # import dopo _bootstrap_paths
    secret_file = get_data_dir() / "secret.key"
    if secret_file.is_file():
        val = secret_file.read_text(encoding="utf-8").strip()
        if len(val) >= 32:
            return val
    import secrets
    val = secrets.token_urlsafe(48)
    secret_file.write_text(val, encoding="utf-8")
    try:
        os.chmod(secret_file, 0o600)
    except Exception:
        pass
    return val


def _prepare_env() -> None:
    os.environ.setdefault("DESKTOP_MODE", "1")
    # APP_ENV non 'production': niente requisiti web (CORS, ecc.)
    os.environ.setdefault("APP_ENV", "desktop")
    # L'app desktop può non essere accesa all'orario dello scheduler notturno →
    # aggiorna i prezzi all'avvio (in background).
    os.environ.setdefault("REFRESH_ON_STARTUP", "1")
    if not os.getenv("SECRET_KEY"):
        os.environ["SECRET_KEY"] = _load_or_create_secret()


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(port: int):
    """Avvia uvicorn in un thread daemon. Ritorna l'oggetto server (per fermarlo)."""
    import uvicorn
    from app.main import app  # import dopo _prepare_env

    # Implementazioni fisse (h11 / asyncio, niente websockets): deterministico e
    # con meno import dinamici da impacchettare in PyInstaller.
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        loop="asyncio", http="h11", ws="none",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def wait_healthy(port: int, timeout: float = 30.0) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def main() -> int:
    _bootstrap_paths()
    _prepare_env()

    port = free_port()
    server = start_server(port)
    if not wait_healthy(port):
        print("Errore: il backend non ha risposto in tempo.", file=sys.stderr)
        return 1

    import webview  # importato solo qui: non serve per i test della logica server
    url = f"http://127.0.0.1:{port}/"
    webview.create_window(APP_NAME, url, width=1280, height=820, min_size=(900, 600))
    webview.start()  # blocca finché la finestra è aperta

    # Finestra chiusa → spegni il server.
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
