#!/usr/bin/env python3
"""Chequeo de salud del contenedor `servidor`, usado por HEALTHCHECK (Dockerfile).

Un `uvicorn` colgado (sin crashear) no se detecta con `restart: unless-stopped`
porque el proceso sigue "vivo" aunque no responda. Este script pega a
`/health/ready` y le da a Docker una señal real de si el proceso sigue
sirviendo: esa ruta además hace `SELECT 1` contra MySQL, así que una base de
datos colgada también deja el contenedor "unhealthy".

Respeta TLS_CERT_PATH/TLS_KEY_PATH (ver docker-entrypoint.sh): si están
configuradas, uvicorn sirve HTTPS en el mismo puerto y hay que pegarle con
ese esquema. La verificación del certificado se desactiva a propósito: el
CA es interno/autofirmado (scripts/generar_ca.sh) y este chequeo corre
dentro del mismo contenedor contra localhost, así que no hay MITM posible.
"""
import os
import ssl
import sys
import urllib.request

scheme = "https" if os.environ.get("TLS_CERT_PATH") else "http"
url = f"{scheme}://localhost:8000/health/ready"

ctx = None
if scheme == "https":
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

try:
    # url es fija (localhost:8000/health/ready), no viene de input externo.
    with urllib.request.urlopen(url, timeout=3, context=ctx) as resp:  # nosec B310
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
