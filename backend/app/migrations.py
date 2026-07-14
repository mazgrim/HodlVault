"""
Migrazioni schema SQLite senza Alembic.

Versione dello schema tracciata con `PRAGMA user_version` (intero nell'header del
DB, nessuna tabella extra). Ad ogni avvio `run_migrations` applica in ordine le
migrazioni pendenti da `user_version` fino a `TARGET_VERSION`.

Garanzie (richieste esplicite):
  1. **Atomicità** — ogni migrazione gira in una singola transazione aperta a
     mano sulla connessione DB-API (`BEGIN … COMMIT/ROLLBACK`). Se fallisce a
     metà, il rollback annulla TUTTO (SQLite supporta il DDL transazionale) e il
     `user_version` non avanza: il DB non resta mai in uno stato ibrido.
  2. **Backup preventivo** — prima di applicare qualsiasi migrazione a un DB che
     contiene già dati, viene fatta una copia del file `.db` in `data/backups/`.

Le migrazioni ricevono un cursore DB-API grezzo e usano `cur.execute(sql)`.
Devono essere **idempotenti** dove possibile (es. controllare l'esistenza di una
colonna prima di aggiungerla), così girano indifferentemente su un DB nuovo
(creato da `create_all`) o su uno vecchio.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Alza questo numero quando aggiungi una migrazione in MIGRATIONS.
TARGET_VERSION = 2


# ── Migrazioni ────────────────────────────────────────────────────────────────

def _migration_1_baseline(cur):
    """
    Baseline: normalizza le colonne di `dividend_events` (lordo/tasse/rateo),
    assorbendo il vecchio `_ensure_dividend_columns`. Idempotente: aggiunge solo
    le colonne mancanti e fa il backfill del lordo per le righe storiche.
    """
    new_cols = {
        "gross_amount": "FLOAT",
        "foreign_tax_amount": "FLOAT DEFAULT 0.0",
        "tax_amount": "FLOAT DEFAULT 0.0",
        "accrued_interest": "FLOAT DEFAULT 0.0",
    }
    existing = {row[1] for row in cur.execute("PRAGMA table_info(dividend_events)").fetchall()}
    for col, ddl in new_cols.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE dividend_events ADD COLUMN {col} {ddl}")
    cur.execute("UPDATE dividend_events SET gross_amount = amount WHERE gross_amount IS NULL")


def _migration_2_price_sources(cur):
    """
    Fonti prezzo alternative a Yahoo (manuale / endpoint JSON custom) e piano
    cedolare dei certificati. Aggiunge le colonne di configurazione su
    `instruments`; tutti gli strumenti esistenti restano 'YAHOO'. La tabella
    `coupon_schedules` è creata da Base.metadata.create_all (gira prima delle
    migrazioni), quindi qui non serve alcun CREATE TABLE.
    """
    new_cols = {
        "price_source": "VARCHAR(11) NOT NULL DEFAULT 'YAHOO'",
        "custom_url": "TEXT",
        "custom_jsonpath_price": "VARCHAR(256)",
        "custom_jsonpath_date": "VARCHAR(256)",
        "price_fetch_error": "TEXT",
        "price_fetch_error_at": "DATETIME",
    }
    existing = {row[1] for row in cur.execute("PRAGMA table_info(instruments)").fetchall()}
    for col, ddl in new_cols.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE instruments ADD COLUMN {col} {ddl}")
    cur.execute("UPDATE instruments SET price_source = 'YAHOO' WHERE price_source IS NULL")


# Mappa versione → funzione. Le chiavi devono essere consecutive a partire da 1.
MIGRATIONS = {
    1: _migration_1_baseline,
    2: _migration_2_price_sources,
}


# ── Runner ────────────────────────────────────────────────────────────────────

def _db_path_from_engine(engine: Engine) -> Path | None:
    if engine.url.get_backend_name() != "sqlite":
        return None
    name = engine.url.database
    if not name or name == ":memory:":
        return None
    return Path(name)


def _backup_db_file(db_path: Path, version_from: int) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    backups = db_path.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups / f"{db_path.stem}.v{version_from}.{ts}.bak"
    shutil.copy2(db_path, dest)
    return dest


def run_migrations(engine: Engine, db_pre_existed: bool = False) -> None:
    """
    Porta il DB a `TARGET_VERSION`. `db_pre_existed` indica se il file DB esisteva
    già prima dell'avvio (usato per decidere se fare il backup: un DB appena
    creato non ha dati da proteggere).
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        current = cur.execute("PRAGMA user_version").fetchone()[0] or 0

        if current == TARGET_VERSION:
            return
        if current > TARGET_VERSION:
            logger.warning(
                f"DB user_version={current} > versione app={TARGET_VERSION}: il DB è stato "
                f"scritto da una versione più recente di HodlVault. Migrazioni saltate."
            )
            return

        pending = [v for v in sorted(MIGRATIONS) if current < v <= TARGET_VERSION]

        # Backup PRIMA di toccare qualunque cosa (solo se ci sono dati reali).
        if pending and db_pre_existed:
            # Checkpoint best-effort, nel caso il DB fosse in modalità WAL, così il
            # file copiato è completo. In journal mode "delete" (default) è un no-op.
            try:
                cur.execute("PRAGMA wal_checkpoint(FULL)")
            except Exception:
                pass
            db_path = _db_path_from_engine(engine)
            if db_path is not None:
                dest = _backup_db_file(db_path, current)
                if dest:
                    logger.info(f"Backup DB pre-migrazione creato: {dest}")

        # Applica ogni migrazione in una transazione a sé.
        for v in pending:
            migrate = MIGRATIONS[v]
            try:
                cur.execute("BEGIN")
                migrate(cur)
                cur.execute(f"PRAGMA user_version = {v}")
                raw.commit()
                logger.info(f"Migrazione DB v{v} applicata.")
            except Exception:
                raw.rollback()
                logger.error(f"Migrazione DB v{v} fallita: rollback eseguito, DB invariato.")
                raise

        # Se non c'erano step ma la versione era indietro (baseline già presente),
        # allinea comunque il contatore.
        if not pending and current < TARGET_VERSION:
            cur.execute("BEGIN")
            cur.execute(f"PRAGMA user_version = {TARGET_VERSION}")
            raw.commit()
    finally:
        raw.close()
