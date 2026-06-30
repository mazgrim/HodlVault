#!/usr/bin/env bash
#
# Backup giornaliero di HodlVault: database (volume Docker) + file .env,
# con rotazione automatica. Pensato per girare da cron come root
# (Docker richiede privilegi). Vedi la sezione "Backup & ripristino" del README.
#
set -euo pipefail

# ── Configurazione (modifica questi valori) ─────────────────────────
VOLUME="hodlvault_hodlvault_data"      # nome del volume Docker (verifica: docker volume ls)
REPO_DIR="/home/hodlvault/HodlVault"   # cartella con docker-compose.yml e .env
BACKUP_DIR="/data/hodlvault_backup"    # dove salvare i backup (es. disco esterno)
KEEP=30                                 # quanti backup giornalieri conservare
# ────────────────────────────────────────────────────────────────────

STAMP="$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# 1) Database: dal volume (sola lettura) → tar.gz sul disco di backup
docker run --rm \
  -v "$VOLUME":/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine \
  tar czf "/backup/hodlvault-backup-$STAMP.tar.gz" -C /data .

# 2) File .env: copia protetta (contiene SECRET_KEY)
cp "$REPO_DIR/.env" "$BACKUP_DIR/env-$STAMP.bak"
chmod 600 "$BACKUP_DIR/env-$STAMP.bak"

# 3) Rotazione: tieni solo gli ultimi $KEEP di ciascun tipo, elimina i più vecchi
ls -1t "$BACKUP_DIR"/hodlvault-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f || true
ls -1t "$BACKUP_DIR"/env-*.bak               2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f || true

echo "[$(date '+%F %T')] Backup completato: $STAMP"
