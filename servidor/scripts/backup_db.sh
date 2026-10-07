#!/usr/bin/env bash
set -euo pipefail

# Backup de la base MySQL de este stack de Docker Compose (dev o prod). No
# había ningún mecanismo de backup/restore del volumen `db_data` en el repo
# -- este script lo cubre con `mysqldump` vía `docker compose exec`, sin
# necesidad de acceso directo al volumen ni de detener el contenedor.
#
# Corré este script desde la raíz del repo (donde están los docker-compose*.yml
# y normalmente el .env).
#
# Uso:
#   ./servidor/scripts/backup_db.sh [directorio-salida] [archivo-compose]
#
# Ejemplo (producción, backup diario vía cron a las 3am):
#   0 3 * * * cd /ruta/al/repo && ./servidor/scripts/backup_db.sh /ruta/a/backups docker-compose.prod.yml >> /var/log/biblioteca-backup.log 2>&1
#
# Variables de entorno (mismas que .env, ver docs/desarrollo/despliegue.md):
#   DB_NAME, DB_USER, DB_PASSWORD -- si no están ya en el entorno, se leen
#   de .env en el directorio actual, igual que hace `docker compose up`.
#
# Retención: conserva los últimos $KEEP backups (14 por defecto, ~2 semanas
# con corridas diarias) y borra el resto -- así el disco no se llena solo.
#
# Restaurar un backup: ./servidor/scripts/restore_db.sh <archivo.sql.gz>

DIR_SALIDA="${1:-./backups}"
COMPOSE_FILE="${2:-docker-compose.prod.yml}"
KEEP="${KEEP:-14}"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "No se encontró '$COMPOSE_FILE'. Corré este script desde la raíz del repo," >&2
    echo "o pasale la ruta correcta como segundo argumento." >&2
    exit 1
fi

# shellcheck disable=SC1091
[ -f .env ] && source .env

: "${DB_NAME:?Falta DB_NAME (en el entorno o en .env)}"
: "${DB_USER:?Falta DB_USER (en el entorno o en .env)}"
: "${DB_PASSWORD:?Falta DB_PASSWORD (en el entorno o en .env)}"

mkdir -p "$DIR_SALIDA"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVO="$DIR_SALIDA/${DB_NAME}-${TIMESTAMP}.sql.gz"

echo "Volcando '$DB_NAME' a $ARCHIVO..."
# MYSQL_PWD (en vez de -p"$DB_PASSWORD") para que la contraseña no quede
# visible en `ps aux` dentro del contenedor mientras corre mysqldump.
# --no-tablespaces: el usuario de la app no tiene el privilegio global PROCESS
# y la base no usa tablespaces propios; sin el flag mysqldump avisa con un error.
docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$DB_PASSWORD" db \
    mysqldump -u "$DB_USER" --single-transaction --routines --no-tablespaces "$DB_NAME" \
    | gzip > "$ARCHIVO"

echo "Listo: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"

# Retención: borra los backups de esta misma base más viejos que los $KEEP
# más recientes (no toca backups de otras bases si $DIR_SALIDA se comparte).
mapfile -t VIEJOS < <(ls -1t "$DIR_SALIDA"/"${DB_NAME}"-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)))
if [ "${#VIEJOS[@]}" -gt 0 ]; then
    echo "Borrando ${#VIEJOS[@]} backup(s) más viejo(s) que los últimos $KEEP..."
    rm -f -- "${VIEJOS[@]}"
fi
