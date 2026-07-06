"""
Risoluzione della cartella dati (dove vive `hodlvault.db`).

Un'unica funzione decide dove stanno i dati a seconda di *come* gira l'app:

  • `DATABASE_URL` / `HODLVAULT_DATA_DIR` impostati (Docker, setup avanzati)
        → vince l'override, comportamento invariato.
  • Bundle desktop (PyInstaller, `sys.frozen`):
        - Windows  → `<cartella .exe>/data` (portable); fallback `%APPDATA%/HodlVault`
                     se quella cartella non è scrivibile (es. Program Files).
        - Linux    → `$XDG_DATA_HOME/HodlVault`  (default `~/.local/share/HodlVault`)
        - macOS    → `~/Library/Application Support/HodlVault`
  • Dev / non-frozen (incluso Docker senza env dedicata) → `./data` come sempre.

NB: in one-file PyInstaller il path va risolto da `sys.executable` (posizione
reale dell'eseguibile), MAI da `sys._MEIPASS` (cartella temporanea cancellata
alla chiusura).
"""
import os
import sys
from pathlib import Path

APP_NAME = "HodlVault"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _writable(path: Path) -> bool:
    """La cartella (creandola se serve) è scrivibile?"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def get_data_dir() -> Path:
    """Cartella dati effettiva (creata se non esiste)."""
    override = os.getenv("HODLVAULT_DATA_DIR")
    if override:
        return _ensure(Path(override))

    if _is_frozen():
        if sys.platform.startswith("win"):
            exe_dir = Path(sys.executable).resolve().parent
            portable = exe_dir / "data"
            if _writable(portable):
                return portable
            # Fallback installato: %APPDATA%\HodlVault
            base = Path(os.getenv("APPDATA") or Path.home()) / APP_NAME
            return _ensure(base)
        if sys.platform == "darwin":
            return _ensure(Path.home() / "Library" / "Application Support" / APP_NAME)
        # Linux / altri: XDG
        xdg = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return _ensure(Path(xdg) / APP_NAME)

    # Dev / Docker-senza-env: comportamento storico.
    return _ensure(Path("./data").resolve())


def get_db_path() -> Path:
    return get_data_dir() / "hodlvault.db"


def get_database_url() -> str:
    """URL SQLAlchemy per il DB SQLite nella cartella dati risolta."""
    return "sqlite:///" + str(get_db_path()).replace("\\", "/")
