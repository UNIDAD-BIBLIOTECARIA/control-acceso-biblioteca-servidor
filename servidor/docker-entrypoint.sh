#!/bin/sh
# Entrypoint del contenedor `servidor`.
#
# Si docker-compose (u otro caller) pasa un comando explícito — como hace
# docker-compose.yml (desarrollo) con `command: ["uvicorn", ..., "--reload"]`
# — se ejecuta tal cual, sin tocarlo: así el flujo de desarrollo actual no
# cambia en nada.
#
# Si no se pasa comando (caso de docker-compose.prod.yml, que no define
# `command:`), arma la invocación de uvicorn acá mismo, agregando
# --ssl-certfile/--ssl-keyfile cuando TLS_CERT_PATH/TLS_KEY_PATH están
# configuradas (ver scripts/generar_ca.sh y docs/desarrollo/despliegue.md,
# sección TLS): sin esto, el tráfico entre los kioscos y este servidor viaja
# sin cifrar por la LAN.
set -e

# El rate limiting de /auth/login y las ventanas de lecturas/escrituras de kiosko
# (servidor/routers/auth.py) se llevan en memoria de este proceso, no en un almacén
# compartido: con más de un worker cada uno tendría su propio contador y sería fácil de
# esquivar. UVICORN_WORKERS no se usa para nada hoy (nunca se le agrega --workers a
# uvicorn más abajo), así que cualquier valor distinto de 1 solo puede ser un intento de
# escalar sin haber migrado antes ese estado — mejor abortar acá con un mensaje claro que
# dejar el rate limiting roto en silencio.
if [ -n "${UVICORN_WORKERS:-}" ] && [ "${UVICORN_WORKERS}" != "1" ]; then
    echo "UVICORN_WORKERS=${UVICORN_WORKERS} no está soportado: el rate limiting de este servidor vive en memoria de un solo proceso (ver servidor/routers/auth.py). Corré un solo worker, o migrá ese estado a un almacén compartido antes de escalar. Abortando." >&2
    exit 1
fi

# La clave privada de la CA interna nunca debe estar al alcance del contenedor:
# quien lo comprometa podría firmar certificados que los kioscos aceptarían
# como del servidor. scripts/generar_ca.sh la deja fuera del directorio de
# certs que monta docker-compose.prod.yml; si aparece acá es que alguien la
# copió por error.
for ca_key in /certs/ca.key "$(dirname "${TLS_KEY_PATH:-/certs/x}")/ca.key"; do
    if [ -e "$ca_key" ]; then
        echo "Se encontró la clave privada de la CA ($ca_key) dentro del contenedor. Sacala del directorio de certs montado (TLS_CERTS_DIR) y guardala offline; el servidor solo necesita server.key/server.pem. Abortando." >&2
        exit 1
    fi
done

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

ARGS="main:app --host 0.0.0.0 --port 8000"

if [ "${UVICORN_RELOAD:-}" = "1" ] || [ "${UVICORN_RELOAD:-}" = "true" ]; then
    ARGS="$ARGS --reload"
fi

if [ -n "${TLS_CERT_PATH:-}" ] && [ -n "${TLS_KEY_PATH:-}" ]; then
    if [ ! -f "$TLS_CERT_PATH" ] || [ ! -f "$TLS_KEY_PATH" ]; then
        echo "TLS_CERT_PATH/TLS_KEY_PATH están configuradas pero el archivo no existe (¿montaste el volumen de certs?) — abortando." >&2
        exit 1
    fi
    ARGS="$ARGS --ssl-certfile $TLS_CERT_PATH --ssl-keyfile $TLS_KEY_PATH"
elif [ -n "${TLS_CERT_PATH:-}" ] || [ -n "${TLS_KEY_PATH:-}" ]; then
    echo "Solo una de TLS_CERT_PATH/TLS_KEY_PATH está configurada — hacen falta las dos, o ninguna. Abortando." >&2
    exit 1
fi

# shellcheck disable=SC2086  # $ARGS se arma en este script, sin datos externos sin validar
exec uvicorn $ARGS
