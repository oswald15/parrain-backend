#!/bin/sh
# Point d'entree du conteneur backend en production (compose.prod.yml).
# Enchaine : migrations -> collecte des fichiers statiques -> gunicorn.
#
# Les migrations tournent a chaque demarrage du conteneur : elles sont idempotentes,
# et c'est le seul moyen de ne pas oublier de les appliquer lors d'une mise a jour.
# Ne pas lancer plusieurs replicas du service backend : ils joueraient les migrations
# en concurrence.
set -e

echo "[entrypoint] migrations..."
python manage.py migrate --noinput

# DEBUG=False : Django ne sert plus les fichiers statiques lui-meme. Ils sont copies
# dans /app/staticfiles (bind-monte cote hote) d'ou Nginx les sert directement.
echo "[entrypoint] collectstatic..."
python manage.py collectstatic --noinput

echo "[entrypoint] gunicorn..."
# --timeout 120 : la generation des factures PDF (xhtml2pdf) peut depasser les 30 s
# par defaut sur un petit VPS.
exec gunicorn le_parrain.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
