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
TARGET_VERSION = 6


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


def _migration_3_minus_compensation(cur):
    """
    Flag "compensazione minusvalenza" sugli incassi (cedole certificati): quando
    attivo l'imposta è assorbita dallo zainetto fiscale e il netto coincide col
    lordo. Gli eventi esistenti restano non compensati.
    """
    existing = {row[1] for row in cur.execute("PRAGMA table_info(dividend_events)").fetchall()}
    if "minus_compensation" not in existing:
        cur.execute("ALTER TABLE dividend_events ADD COLUMN minus_compensation BOOLEAN NOT NULL DEFAULT 0")


def _migration_4_dividend_source(cur):
    """
    Traccia l'origine di ogni incasso (`dividend_events.source`) per la regola
    'broker se presente, altrimenti Yahoo'. Backfill delle righe storiche (prima
    di questa versione l'origine non era registrata):

      - CERT_COUPON          → 'COUPON'  (conferma piano cedole certificati)
      - foreign_tax_amount>0 → 'YAHOO'   (vedi sotto)
      - tutto il resto       → 'IMPORT'  (default della colonna)

    Marcatore affidabile: SOLO il sync Yahoo (`DividendCalculator.sync_from_market`
    via `compute_net`) scrive una ritenuta estera in `foreign_tax_amount`. Tutti
    gli import broker storici (Fineco/Directa/Trade Republic) azzeravano quel campo
    e mettevano l'eventuale tassa in `tax_amount`. Quindi `foreign_tax_amount > 0`
    identifica univocamente il sync Yahoo, senza confondere un dividendo TR estero
    (USD, cambio reale) con uno Yahoo. Resta un solo caso ambiguo — un dividendo
    Yahoo da un paese senza ritenuta (foreign_tax=0) — che ricade in 'IMPORT': è
    innocuo, da qui in avanti l'origine è scritta esplicitamente a ogni creazione.
    """
    existing = {row[1] for row in cur.execute("PRAGMA table_info(dividend_events)").fetchall()}
    if "source" not in existing:
        cur.execute(
            "ALTER TABLE dividend_events ADD COLUMN source VARCHAR(8) NOT NULL DEFAULT 'IMPORT'"
        )
    # Backfill (la colonna nasce a 'IMPORT', qui promuoviamo COUPON e YAHOO).
    cur.execute("UPDATE dividend_events SET source = 'COUPON' WHERE type = 'CERT_COUPON'")
    cur.execute(
        "UPDATE dividend_events SET source = 'YAHOO' "
        "WHERE type <> 'CERT_COUPON' AND foreign_tax_amount > 0"
    )


def _migration_5_dividend_unique_index(cur):
    """
    Ripristina il vincolo di unicità dei dividendi. `uq_dividend_event`
    (un incasso per portafoglio/strumento/data/tipo) è dichiarato nel modello, ma
    i DB creati prima che venisse aggiunto NON lo hanno (create_all non aggiunge
    vincoli a tabelle già esistenti). Il sync Yahoo si affidava a quel vincolo per
    non duplicare: senza, ri-creava lo stesso dividendo a ogni esecuzione.

    Qui: 1) rimuove i duplicati esatti tenendo la riga con id minore; 2) crea
    l'indice UNIQUE, così il vincolo è finalmente applicato a ogni percorso.
    Idempotente.
    """
    cur.execute(
        "DELETE FROM dividend_events WHERE id NOT IN ("
        "  SELECT MIN(id) FROM dividend_events"
        "  GROUP BY portfolio_id, instrument_id, date, type"
        ")"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dividend_event "
        "ON dividend_events (portfolio_id, instrument_id, date, type)"
    )


def _migration_6_isin_not_unique(cur):
    """
    Consente più quotazioni con lo stesso ISIN (ticker/exchange diversi: es. MSTR
    su Nasdaq in USD e MIGA.SG su Stoccarda in EUR). L'ISIN era UNIQUE, quindi il
    secondo import con lo stesso ISIN riusava lo strumento esistente e ne
    sovrascriveva il ticker, fondendo due posizioni distinte. Qui l'indice UNIQUE
    su `isin` diventa un indice normale; l'identità dello strumento passa al
    TICKER (gestita in get_or_create_instrument). Idempotente.
    """
    cur.execute("DROP INDEX IF EXISTS ix_instruments_isin")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_instruments_isin ON instruments (isin)")


# Mappa versione → funzione. Le chiavi devono essere consecutive a partire da 1.
MIGRATIONS = {
    1: _migration_1_baseline,
    2: _migration_2_price_sources,
    3: _migration_3_minus_compensation,
    4: _migration_4_dividend_source,
    5: _migration_5_dividend_unique_index,
    6: _migration_6_isin_not_unique,
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
