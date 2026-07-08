# HodlVault Desktop

App native single-user, **senza browser**: una finestra nativa (pywebview) mostra
l'interfaccia mentre il backend FastAPI gira in locale su una porta effimera.
Stesso codice di Docker/web — cambia solo il modo di avviare e impacchettare.

## Download (senza compilare nulla)
Gli eseguibili sono pubblicati nelle [Releases](../../releases): scarica
`HodlVault.exe` (Windows, portable) o `HodlVault-x86_64.AppImage` (Linux).
Li costruisce GitHub Actions al push di un tag `v*` (vedi
`.github/workflows/release.yml`); compilare in locale serve solo per sviluppare.

> **Avviso di Windows.** L'eseguibile non è firmato digitalmente, quindi SmartScreen
> mostra *"Windows ha protetto il PC"*. Clicca **Ulteriori informazioni → Esegui
> comunque**. Un certificato di code signing è a pagamento; il sorgente è tutto qui.
> Per lo stesso motivo alcuni antivirus segnalano euristicamente i binari
> PyInstaller: per ridurre i falsi positivi la compressione UPX è disattivata.

## Come funziona
Al **primo avvio** l'app chiede solo un nome utente (nessuna password) e crea il
profilo locale; agli avvii successivi entra da sola. Essendo single-user, le
funzioni di amministrazione sono nascoste.

`launcher.py`:
1. imposta `DESKTOP_MODE=1` (login passwordless single-user) e una `SECRET_KEY`
   stabile persistita nella cartella dati;
2. avvia uvicorn su `127.0.0.1:<porta libera>` in un thread;
3. attesa di `/api/health`, poi apre la finestra pywebview sull'app;
4. alla chiusura della finestra ferma il server.

Il frontend buildato è incluso nel bundle e servito dal backend
(`frontend_static`), quindi non serve nginx/Vite.

## Dove stanno i dati
Risolti da `backend/app/data_dir.py`:
- **Windows (portable)**: `data/` accanto all'eseguibile. Copiando la cartella
  dell'`.exe`, il DB viaggia con essa. Fallback `%APPDATA%\HodlVault` se la
  cartella dell'exe non è scrivibile.
- **Linux (AppImage)**: `~/.local/share/HodlVault` (XDG).
- Override: `HODLVAULT_DATA_DIR`.

Il DB SQLite (`hodlvault.db`), i backup pre-migrazione (`backups/`) e `secret.key`
stanno tutti lì. Per spostare i dati fra installazioni usa Backup → Esporta/Importa
(formato JSON versionato).

## Aggiornamento prezzi
Lo scheduler notturno (18:00) non gira ad app chiusa, quindi in desktop mode il
launcher imposta `REFRESH_ON_STARTUP=1`: all'avvio i prezzi vengono aggiornati in
background (non blocca la UI). Resta disponibile il pulsante "Aggiorna prezzi".
In Docker/web l'env è assente → nessun refresh all'avvio.

## Migrazioni schema
All'avvio `migrations.run_migrations` porta il DB all'ultima versione. Ogni
migrazione è **atomica** (rollback totale se fallisce) e prima di applicarle a un
DB con dati viene copiato il file `.db` in `data/backups/`.

## Build

### Windows (`HodlVault.exe` portable)
```powershell
# dalla radice del repo, in un venv Python 3.12+
.\desktop\build-windows.ps1
# -> dist\HodlVault.exe
```

### Linux (`HodlVault-x86_64.AppImage`)
```bash
# richiede GTK+WebKit2GTK e appimagetool nel PATH
./desktop/build-appimage.sh
# -> dist/HodlVault-x86_64.AppImage
```

Le build vanno prodotte **sul sistema operativo di destinazione** (niente
cross-compile).

## Lanciare in sviluppo (senza impacchettare)
```bash
cd frontend && npm run build && cd ..        # opzionale: per servire la UI dal backend
pip install -r backend/requirements.txt -r desktop/requirements-desktop.txt
python desktop/launcher.py
```

## Note
- Icona: metti `desktop/icon.ico` (Windows) e/o `desktop/icon.png` (Linux) prima
  del build; sono opzionali.
- Debug primo build: in `hodlvault.spec` imposta `console=True` per vedere i log.
- pywebview su Linux richiede i runtime GUI di sistema (vedi
  `requirements-desktop.txt`).
