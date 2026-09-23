#!/usr/bin/env bash
set -euo pipefail

# Renueva SOLO el certificado de servidor (server.key/server.pem), reusando
# la CA interna ya existente (ca.key/ca.pem) generada por generar_ca.sh.
# A diferencia de correr generar_ca.sh otra vez (que exige borrar la CA a
# mano y generaría una CA NUEVA), esto no invalida la confianza que ya
# tienen configurada los kioscos -- ca.pem no cambia, así que no hace falta
# volver a copiarlo a ninguno de los 16 kioscos.
#
# Uso:
#   ./servidor/scripts/renovar_cert_servidor.sh <IP-o-hostname-del-servidor> [directorio-certs] [directorio-ca]
#
# Por defecto usa <raíz del repo>/certs y <raíz del repo>/ca (mismos defaults
# que generar_ca.sh). Si guardaste ca.key offline, traela temporalmente al
# directorio de la CA (o pasá su ruta como tercer argumento) y volvé a
# retirarla al terminar — nunca al directorio de certs, que se monta dentro
# del contenedor.
# server.key/server.pem viejos quedan respaldados como server.key.bak /
# server.pem.bak (se sobreescribe el respaldo anterior si corrés esto dos
# veces sin borrarlos).

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl no está instalado." >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <IP-o-hostname-del-servidor> [directorio-certs] [directorio-ca]" >&2
    echo "Ejemplo: $0 192.168.10.5" >&2
    exit 1
fi

HOST="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${2:-$SCRIPT_DIR/../../certs}"
CA_DIR="${3:-$SCRIPT_DIR/../../ca}"

if [[ ! -f "$CA_DIR/ca.key" || ! -f "$CA_DIR/ca.pem" ]]; then
    echo "No se encontró una CA en $CA_DIR (ca.key/ca.pem)." >&2
    echo "Este script renueva el certificado de servidor reusando una CA ya" >&2
    echo "generada -- para crear la CA por primera vez, usá generar_ca.sh." >&2
    echo "Si ca.key está guardada offline, pasá su directorio como tercer argumento." >&2
    exit 1
fi

if [[ ! -d "$OUT_DIR" ]]; then
    echo "No existe el directorio de certs $OUT_DIR." >&2
    exit 1
fi

OUT_DIR="$(cd "$OUT_DIR" && pwd)"
CA_DIR="$(cd "$CA_DIR" && pwd)"

if [[ "$OUT_DIR" == "$CA_DIR" ]]; then
    echo "ERROR: el directorio de la CA no puede ser el mismo que el de certs" >&2
    echo "($OUT_DIR): ese se monta dentro del contenedor y ca.key no debe estar ahí." >&2
    exit 1
fi

cd "$OUT_DIR"

if [[ -f server.key || -f server.pem ]]; then
    echo "Respaldando server.key/server.pem actuales como *.bak..."
    cp -f server.key server.key.bak 2>/dev/null || true
    cp -f server.pem server.pem.bak 2>/dev/null || true
fi

echo "=== Emitiendo nuevo certificado de servidor para '$HOST' (misma CA) ==="
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=$HOST"

if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:$HOST"
else
    SAN="DNS:$HOST"
fi
openssl x509 -req -in server.csr -CA "$CA_DIR/ca.pem" -CAkey "$CA_DIR/ca.key" -CAcreateserial \
    -out server.pem -days 825 -sha256 \
    -extfile <(printf "subjectAltName=%s" "$SAN")
rm -f server.csr "$CA_DIR/ca.srl"

chmod 600 server.key
chmod 644 server.pem

echo ""
echo "=== Listo ==="
echo "server.key/server.pem renovados en $OUT_DIR (vencen en ~825 días)."
echo "ca.pem NO cambió -- los kioscos ya configurados siguen confiando en este"
echo "certificado sin ningún cambio de su lado."
echo ""
echo "Si trajiste ca.key desde el respaldo offline, retirala de nuevo de esta PC."
echo ""
echo "Reiniciá el contenedor 'servidor' para que uvicorn cargue el certificado nuevo:"
echo "  docker compose -f docker-compose.prod.yml restart servidor"
