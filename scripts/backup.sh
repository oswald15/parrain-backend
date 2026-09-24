#!/usr/bin/env bash
#
# Sauvegarde de la base et des fichiers media.
#
# Devient critique des lors que le serveur est heberge dans le bar : la machine sur place est
# alors le SEUL exemplaire des donnees, et le materiel grand public tombe en panne. Aujourd'hui
# les sauvegardes sont manuelles et sporadiques (un dump isole dans backups/).
#
# Usage :
#   ./scripts/backup.sh                    # sauvegarde locale
#   REMOTE_DEST=user@hote:/chemin ./scripts/backup.sh   # + copie hors site
#
# Planification (tous les jours a 3h), sur la machine qui heberge les conteneurs :
#   0 3 * * * cd /chemin/vers/le_parrain-main && ./scripts/backup.sh >> backups/backup.log 2>&1

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
REMOTE_DEST="${REMOTE_DEST:-}"

if [ ! -f .env ]; then
  echo "ERREUR : fichier .env introuvable, impossible de lire les acces a la base." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

: "${DB_NAME:?DB_NAME absent du .env}"
: "${DB_USER:?DB_USER absent du .env}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
DB_FILE="$BACKUP_DIR/db_${STAMP}.sql.gz"
MEDIA_FILE="$BACKUP_DIR/media_${STAMP}.tar.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Debut de la sauvegarde"

# --- Base de donnees ---------------------------------------------------------
# Ecriture dans un fichier temporaire d'abord : un dump interrompu ne doit jamais remplacer
# une sauvegarde valide, ni etre pris pour une sauvegarde complete au moment de restaurer.
TMP_DB="${DB_FILE}.partial"
if ! docker compose -f "$COMPOSE_FILE" exec -T db \
      pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$TMP_DB"; then
  echo "ERREUR : le dump PostgreSQL a echoue." >&2
  rm -f "$TMP_DB"
  exit 1
fi

# Un dump vide ou minuscule signale un echec silencieux (conteneur arrete, mauvais identifiants).
if [ ! -s "$TMP_DB" ] || [ "$(stat -c%s "$TMP_DB" 2>/dev/null || stat -f%z "$TMP_DB")" -lt 1000 ]; then
  echo "ERREUR : le dump produit est anormalement petit, sauvegarde abandonnee." >&2
  rm -f "$TMP_DB"
  exit 1
fi
mv "$TMP_DB" "$DB_FILE"
echo "  base    -> $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"

# --- Fichiers media (images produits) ----------------------------------------
if [ -d media ]; then
  tar czf "$MEDIA_FILE" media
  echo "  media   -> $MEDIA_FILE ($(du -h "$MEDIA_FILE" | cut -f1))"
else
  echo "  media   -> ignore (dossier absent)"
fi

# --- Copie hors site ---------------------------------------------------------
# Volontairement non bloquante : sans internet, la sauvegarde locale reste valide et le script
# ne doit pas signaler un echec qui ferait passer les suivantes pour inutiles.
if [ -n "$REMOTE_DEST" ]; then
  if scp "$DB_FILE" ${MEDIA_FILE:+"$MEDIA_FILE"} "$REMOTE_DEST" 2>/dev/null; then
    echo "  hors site -> $REMOTE_DEST"
  else
    echo "  AVERTISSEMENT : copie hors site impossible (internet coupe ?). Sauvegarde locale conservee."
  fi
fi

# --- Rotation ----------------------------------------------------------------
# Apres coup uniquement : purger avant le dump risquerait de supprimer les anciennes
# sauvegardes puis d'echouer, ne laissant plus rien.
find "$BACKUP_DIR" -name 'db_*.sql.gz' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name 'media_*.tar.gz' -mtime "+$RETENTION_DAYS" -delete

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sauvegarde terminee (retention : $RETENTION_DAYS jours)"
