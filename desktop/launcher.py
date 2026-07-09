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
WINDOW_BG = "#0F0F1A"   # navy-900 del tema scuro (evita il flash bianco all'avvio)


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
    # Forza il DB nella cartella dati portable/AppData PRIMA che app.main chiami
    # load_dotenv(): così un .env vicino all'eseguibile (es. quello del repo)
    # non dirotta il database. load_dotenv non sovrascrive le variabili già
    # impostate, quindi questo valore vince.
    from app.data_dir import get_database_url
    os.environ.setdefault("DATABASE_URL", get_database_url())
    if not os.getenv("SECRET_KEY"):
        os.environ["SECRET_KEY"] = _load_or_create_secret()


def _redirect_std_streams() -> None:
    """
    Nelle build windowed (console=False) sys.stdout/stderr sono None: qualsiasi
    logging (o l'isatty() di uvicorn) va in crash. Li reindirizziamo a un file di
    log nella cartella dati — così l'app parte e abbiamo i log per il debug.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from app.data_dir import get_data_dir
        log_path = get_data_dir() / "desktop.log"
        f = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        import io
        f = io.StringIO()  # ultima spiaggia: evita comunque il None
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _restore_system_library_path() -> None:
    """
    Ripristina LD_LIBRARY_PATH all'originale prima di avviare la webview.

    Il bootloader PyInstaller punta LD_LIBRARY_PATH alla cartella del bundle
    (_MEIPASS) e salva l'originale in LD_LIBRARY_PATH_ORIG. WebKitGTK, per
    renderizzare, avvia processi FIGLI separati (WebKitNetworkProcess,
    WebKitWebProcess): sono i binari *di sistema*, ma ereditano il nostro
    LD_LIBRARY_PATH e finiscono per caricare le librerie del bundle (libssl,
    libcrypto, libsqlite3… compilate su un'altra distro) invece di quelle di
    sistema. Il mismatch fa morire il processo web → finestra con solo lo
    sfondo, nessun contenuto, e nessun errore nel nostro stdout (il crash è nel
    figlio).

    Il nostro processo ha gia' caricato le sue librerie: ripristinare qui la
    variabile non lo tocca, ma i figli di WebKit useranno le librerie di sistema.
    """
    if not getattr(sys, "frozen", False):
        return
    orig = os.environ.get("LD_LIBRARY_PATH_ORIG")
    if orig is not None:
        os.environ["LD_LIBRARY_PATH"] = orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


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


def _apply_dark_titlebar(window) -> None:
    """
    Barra del titolo scura su Windows 10 (1809+) e 11, mantenendo il frame
    nativo: si imposta l'attributo DWM DWMWA_USE_IMMERSIVE_DARK_MODE sull'HWND.
    Best-effort — qualunque errore qui non deve impedire l'avvio dell'app.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = 0
        # pywebview (backend WinForms) espone la Form nativa con .Handle
        handle = getattr(getattr(window, "native", None), "Handle", None)
        if handle is not None:
            hwnd = int(handle)
        if not hwnd:  # fallback: cerca la finestra per titolo
            hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
        if not hwnd:
            return

        value = ctypes.c_int(1)  # 1 = dark mode
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 e Win10 >= build 18985)
        # 19 = stesso attributo sulle build di Win10 precedenti
        applied = False
        for attr in (20, 19):
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(attr),
                ctypes.byref(value), ctypes.sizeof(value),
            )
            if res == 0:
                applied = True
                break

        # DwmSetWindowAttribute su una finestra GIÀ mostrata imposta l'attributo
        # ma NON ridisegna l'area non-client: la barra resta chiara finché un
        # evento non forza il repaint del frame (es. il primo resize/massimizza —
        # ecco perché diventava scura solo allargando la finestra). Forziamo qui
        # il ricalcolo del frame senza toccare posizione, dimensione o z-order.
        if applied:
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
            SWP_FRAMECHANGED = 0x20
            ctypes.windll.user32.SetWindowPos(
                wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
    except Exception as exc:  # pragma: no cover - dipende dall'OS
        print(f"Barra del titolo scura non applicata: {exc}", file=sys.stderr)


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
    _redirect_std_streams()  # PRIMA di importare/avviare uvicorn (che tocca stdout)

    port = free_port()
    server = start_server(port)
    if not wait_healthy(port):
        print("Errore: il backend non ha risposto in tempo.", file=sys.stderr)
        return 1

    import webview  # importato solo qui: non serve per i test della logica server
    # I processi figli di WebKit devono usare le librerie di sistema, non quelle
    # del bundle: ripristina LD_LIBRARY_PATH prima di far partire la webview.
    _restore_system_library_path()
    url = f"http://127.0.0.1:{port}/"
    window = webview.create_window(
        APP_NAME, url, width=1280, height=820, min_size=(900, 600),
        background_color=WINDOW_BG,   # niente lampo bianco prima del render
    )
    # L'HWND esiste solo a finestra mostrata → applica lì la barra scura.
    window.events.shown += lambda *_: _apply_dark_titlebar(window)

    # private_mode di pywebview è True di default: sessione effimera con storage
    # web non persistente. Su WebKitGTK questo rende `localStorage` inaccessibile
    # (SecurityError sulle origin http://), e il frontend lo usa per i token: la
    # prima getItem lancia, `setLoading(false)` non viene mai raggiunto e resta la
    # schermata di caricamento (navy) all'infinito. private_mode=False + uno
    # storage_path persistente risolve, ed è anche corretto per un'app desktop:
    # cosi' la sessione sopravvive ai riavvii invece di sloggare a ogni chiusura.
    from app.data_dir import get_data_dir
    storage = get_data_dir() / "webview"
    try:
        storage.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    webview.start(  # blocca finché la finestra è aperta
        private_mode=False,
        storage_path=str(storage),
        debug=bool(os.getenv("HODLVAULT_DEBUG")),
    )

    # Finestra chiusa → spegni il server.
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
