#!/usr/bin/env bash
set -euo pipefail

# Restaura un backup generado por backup_db.sh. DESTRUCTIVO: sobreescribe
# los datos actuales de la base con los del archivo indicado.
#
# Corré este script desde la raíz del repo (donde están los docker-compose*.yml
# y normalmente el .env).
#
# Uso:
#   ./servidor/scripts/restore_db.sh <archivo.sql.gz> [archivo-compose]

ARCHIVO="${1:?Uso: restore_db.sh <archivo.sql.gz> [archivo-compose]}"
COMPOSE_FILE="${2:-docker-compose.prod.yml}"

if [ ! -f "$ARCHIVO" ]; then
    echo "No existe '$ARCHIVO'" >&2
    exit 1
fi
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "No se encontró '$COMPOSE_FILE'. Corré este script desde la raíz del repo," >&2
    echo "o pasale la ruta correcta como segundo argumento." >&2
    exit 1
fi

# shellcheck disable=SC1091
[ -f .env ] && source .env

: "${DB_NAME:?Falta DB_NAME (en el entorno o en .env)}"
: "${MYSQL_ROOT_PASSWORD:?Falta MYSQL_ROOT_PASSWORD (en el entorno o en .env)}"

echo "Esto SOBREESCRIBE la base '$DB_NAME' (servicio 'db' de $COMPOSE_FILE) con el"
echo "contenido de '$ARCHIVO'. Los datos actuales de esa base se pierden."
read -r -p "Escribí 'si' para confirmar: " CONFIRMACION
if [ "$CONFIRMACION" != "si" ]; then
    echo "Cancelado."
    exit 1
fi

# Con root y no con el usuario de la app: el volcado hace DROP TABLE y
# LOCK TABLES, que ese usuario no tiene (ver scripts/mysql-init/).
gunzip -c "$ARCHIVO" | docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" db \
    mysql -u root "$DB_NAME"

echo "Restauración completa."
