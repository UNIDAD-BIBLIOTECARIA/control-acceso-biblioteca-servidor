"""Contraseñas que alguna vez aparecieron en texto plano en este repo público
(en `.env.example`, como valor de ejemplo o por error en un commit). Siguen
en el historial de git aunque ya no estén en el árbol actual, así que hay
que darlas por conocidas: cualquiera que haya clonado el repo las tiene.

El servidor se niega a usarlas en vez de confiar solo en que el operador
recuerde no copiarlas: `db/connection.py` no arranca con ellas como
`DB_PASSWORD`, `db/schema.py` no siembra el admin inicial si
`ADMIN_PASS_HASH` corresponde a una de ellas y `PUT /auth/password` no las
acepta como contraseña nueva.

Este módulo no importa nada de la app para poder usarse desde `db/` sin
dependencias circulares con `routers/auth.py`."""

import hashlib
import hmac

CONTRASENAS_PUBLICADAS = frozenset({
    "biblioteca2026",
    "biblioteca2026$",
    "cambia-esta-contrasena",
    "cambia-esta-contrasena-de-db",
    "cambia-esta-contrasena-de-root",
    "cambiar-esta-contrasena",
})


def es_contrasena_publicada(password: str) -> bool:
    return password in CONTRASENAS_PUBLICADAS


def es_hash_de_contrasena_publicada(hash_almacenado: str) -> bool:
    """True si `hash_almacenado` (formato `pbkdf2_sha256$<iter>$<salt>$<hash>`) corresponde a
    alguna de `CONTRASENAS_PUBLICADAS`. Cuesta un PBKDF2 completo por contraseña de la lista, así
    que solo debe usarse en caminos poco frecuentes (el arranque, no el login)."""
    try:
        algoritmo, iteraciones_s, salt_hex, hash_hex = hash_almacenado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        iteraciones, salt = int(iteraciones_s), bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    for password in CONTRASENAS_PUBLICADAS:
        derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iteraciones)
        if hmac.compare_digest(derivado.hex(), hash_hex):
            return True
    return False
