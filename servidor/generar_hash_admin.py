#!/usr/bin/env python3
"""Genera el hash de la contraseña INICIAL del panel de administración.

`ADMIN_USER`/`ADMIN_PASS_HASH` del `.env` solo se usan una vez, para crear
el primer administrador en la base de datos (tabla `admins`) si está vacía
— ver `db/schema.py::_sembrar_admin_inicial`. Después de ese primer login,
el administrador cambia su contraseña desde el panel ("Cambiar contraseña",
`PUT /auth/password`) y el `.env` queda obsoleto.

Este script sirve para fijar esa contraseña inicial sin que quien hace el
despliegue la vea en texto plano: ejecutalo en TU máquina — no en el
servidor de despliegue — y copiale solo la línea `ADMIN_PASS_HASH=...`
resultante (mismo principio que el PIN de administrador del kiosko, ver
../biblioteca_cliente/cliente/setup.py). No uses el hash de ejemplo del
`.env.example`: es público y el servidor se niega a sembrar el admin
inicial con él (`db/schema.py`).

Aplica la misma política que `PUT /auth/password` (longitud entre 12 y 128
caracteres y no estar entre las contraseñas publicadas en el repo), para que
la contraseña inicial no sea más débil que las que el panel aceptaría.

Uso:
    python3 generar_hash_admin.py
"""
import getpass
import hashlib
import secrets
import sys

from contrasenas_publicadas import es_contrasena_publicada

ITERACIONES = 600_000  # recomendación OWASP (2023+) para PBKDF2-HMAC-SHA256
# Mismos límites que PASSWORD_MIN_LONGITUD/PASSWORD_MAX_LONGITUD en routers/auth.py (no se
# importan de ahí porque ese módulo exige SECRET_KEY y la conexión a la BD al importarse).
MIN_LONGITUD = 12
MAX_LONGITUD = 128


def generar_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${salt.hex()}${derivado.hex()}"


def main() -> None:
    password = getpass.getpass("Contraseña de administrador (no se muestra en pantalla): ").strip()
    if not MIN_LONGITUD <= len(password) <= MAX_LONGITUD:
        sys.exit(f"La contraseña debe tener entre {MIN_LONGITUD} y {MAX_LONGITUD} caracteres.")
    if es_contrasena_publicada(password):
        sys.exit("Esa contraseña está publicada en el historial del repo; elegí otra.")
    confirmacion = getpass.getpass("Confírmala: ").strip()
    if password != confirmacion:
        sys.exit("Las contraseñas no coinciden.")

    print("\nAgrega esta línea al .env del servidor:\n")
    # Comillas simples obligatorias: el hash trae "$" como separador
    # (pbkdf2_sha256$iteraciones$salt$hash) y Docker Compose interpola
    # variables dentro de .env — sin comillas, "$" seguido de algo que
    # parezca nombre de variable (p. ej. el salt si empieza con letra) se
    # reemplaza por texto vacío y corrompe el hash silenciosamente.
    print(f"ADMIN_PASS_HASH='{generar_hash(password)}'")
    print("\n(No compartas la contraseña en texto plano — solo esta línea con el hash.)")


if __name__ == "__main__":
    main()
