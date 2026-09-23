#!/usr/bin/env bash
set -euo pipefail

# Genera una CA interna propia y un certificado de servidor firmado por ella,
# para cifrar el tráfico entre los kioscos (biblioteca_cliente) y este
# servidor dentro de la LAN del laboratorio. No hay dominio público, solo
# una IP interna, así que no aplica una CA pública tipo Let's Encrypt — ver
# docs/desarrollo/despliegue.md, sección TLS.
#
# Se corre UNA VEZ en la PC maestra (o en cualquier máquina con openssl, y
# luego copiás los archivos a la PC maestra) — para renovar el certificado
# de servidor cuando esté por vencer, sin tocar la CA ni los kioscos ya
# configurados, ver ./renovar_cert_servidor.sh en su lugar. Para chequear
# cuánto falta para que venza, ver ./verificar_vencimiento_cert.sh.
#
# Uso:
#   ./scripts/generar_ca.sh <IP-o-hostname-del-servidor> [directorio-certs] [directorio-ca]
#
# Ejemplo:
#   ./scripts/generar_ca.sh 192.168.10.5
#
# La CA y el certificado de servidor van a directorios SEPARADOS a propósito:
# docker-compose.prod.yml monta el directorio de certs completo dentro del
# contenedor, y la clave privada de la CA no debe estar ahí — si alguien
# compromete el contenedor, con ca.key podría firmar certificados que los 16
# kioscos aceptarían como válidos y hacerse pasar por el servidor (MITM de
# API keys y PII). El servidor solo necesita server.key/server.pem.
#
# En el directorio de la CA (por defecto <raíz del repo>/ca, fuera del
# volumen montado):
#   ca.key     — clave privada de la CA. GUARDAR OFFLINE (USB, gestor de
#                contraseñas) y borrarla de la PC maestra; NO subir a git.
#                Solo se necesita de nuevo para renovar el certificado de
#                servidor (renovar_cert_servidor.sh).
#   ca.pem     — certificado público de la CA.
#
# En el directorio de certs (por defecto <raíz del repo>/certs, el que monta
# docker-compose.prod.yml en /certs):
#   server.key — clave privada del servidor. Queda en la PC maestra, NUNCA
#                se distribuye a los kioscos. TLS_KEY_PATH en el .env del
#                servidor.
#   server.pem — certificado del servidor firmado por la CA. TLS_CERT_PATH
#                en el .env del servidor.
#   ca.pem     — copia del certificado público de la CA, para tenerla a mano
#                al configurar los kioscos (biblioteca_cliente/cliente/ca.pem,
#                ver config.ini -> [servidor] ca_cert) y para que
#                verificar_vencimiento_cert.sh vigile su vencimiento.

if [[ $# -lt 1 ]]; then
    echo "Uso: $0 <IP-o-hostname-del-servidor> [directorio-certs] [directorio-ca]" >&2
    echo "Ejemplo: $0 192.168.10.5" >&2
    exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl no está instalado." >&2
    exit 1
fi

HOST="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Defaults: <raíz del repo>/certs y <raíz del repo>/ca (junto a
# docker-compose.prod.yml y .env), NO dentro de servidor/ — ese directorio es
# el build context de la imagen Docker (servidor/Dockerfile hace `COPY . .`)
# y no queremos que las claves privadas terminen empacadas ahí adentro por
# accidente.
OUT_DIR="${2:-$SCRIPT_DIR/../../certs}"
CA_DIR="${3:-$SCRIPT_DIR/../../ca}"
mkdir -p "$OUT_DIR" "$CA_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
CA_DIR="$(cd "$CA_DIR" && pwd)"

if [[ "$OUT_DIR" == "$CA_DIR" ]]; then
    echo "ERROR: el directorio de la CA no puede ser el mismo que el de certs" >&2
    echo "($OUT_DIR): ese se monta dentro del contenedor y ca.key no debe estar ahí." >&2
    exit 1
fi

if [[ -f "$CA_DIR/ca.key" || -f "$CA_DIR/ca.pem" ]]; then
    echo "Ya existe una CA en $CA_DIR (ca.key/ca.pem)." >&2
    echo "¿Buscás renovar el certificado de servidor (por vencer)? Usá en cambio:" >&2
    echo "  ./scripts/renovar_cert_servidor.sh <host> -- reusa esta misma CA, sin" >&2
    echo "  tocar los kioscos ya configurados." >&2
    echo "Si en cambio de verdad querés una CA nueva, borrá ca.key/ca.pem a mano —" >&2
    echo "ojo: invalida el certificado de todos los kioscos ya configurados con el" >&2
    echo "ca.pem viejo, hay que volver a copiarles el nuevo." >&2
    exit 1
fi

echo "=== Generando CA interna en $CA_DIR ==="
openssl genrsa -out "$CA_DIR/ca.key" 4096
# -addext keyUsage: sin esta extensión, OpenSSL 3.2+ (validación estricta de
# cadena, ver X509_V_FLAG_X509_STRICT) rechaza este CA para verificar el
# certificado del servidor con "CA cert does not include key usage
# extension" — falla silenciosa en el cliente porque hay_conexion() traga
# cualquier excepción y la reporta solo como "sin conexión".
openssl req -x509 -new -nodes -key "$CA_DIR/ca.key" -sha256 -days 3650 \
    -out "$CA_DIR/ca.pem" -subj "/CN=Biblioteca UES CA" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "basicConstraints=critical,CA:true"

echo ""
echo "=== Generando certificado del servidor para '$HOST' en $OUT_DIR ==="
cd "$OUT_DIR"
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
cp "$CA_DIR/ca.pem" ca.pem

chmod 600 "$CA_DIR/ca.key" server.key
chmod 644 "$CA_DIR/ca.pem" ca.pem server.pem

echo ""
echo "=== Listo ==="
echo "CA en $CA_DIR:"
ls -1 "$CA_DIR"
echo "Certificados para el servidor en $OUT_DIR:"
ls -1 "$OUT_DIR"
echo ""
echo "En el servidor (.env):"
echo "  TLS_CERT_PATH=/certs/server.pem"
echo "  TLS_KEY_PATH=/certs/server.key"
echo "  (docker-compose.prod.yml monta $OUT_DIR en /certs dentro del contenedor —"
echo "   ajustá TLS_CERTS_DIR en el .env si moviste este directorio)"
echo ""
echo "En cada kiosko (biblioteca_cliente):"
echo "  Copiá $OUT_DIR/ca.pem a cliente/ca.pem"
echo "  En config.ini: [servidor] url = https://$HOST:8000 , ca_cert = ca.pem"
echo ""
echo "IMPORTANTE:"
echo "  - $CA_DIR/ca.key es la clave privada de la CA: no la distribuyas, no la"
echo "    subas a git, NO la copies al directorio de certs (se monta dentro del"
echo "    contenedor). Guardala offline y borrala de esta PC; sin ella no podés"
echo "    firmar un futuro certificado de servidor."
echo "  - server.pem vence en ~825 días (2.25 años) — calendarizá su renovación con"
echo "    ./scripts/renovar_cert_servidor.sh (reusa esta misma CA, no hace falta"
echo "    redistribuir nada a los kioscos). ./scripts/verificar_vencimiento_cert.sh"
echo "    avisa cuando falten menos de 60 días — agregalo a cron."
