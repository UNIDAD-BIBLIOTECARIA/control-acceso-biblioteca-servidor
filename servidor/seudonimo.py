"""Seudónimo de un carnet para los logs.

Los logs del servidor (stdout del contenedor, que Docker conserva y que
puede terminar copiado en un ticket o un backup) registran altas, ediciones
y bajas de estudiantes. Con el carnet en claro, esos logs son PII. Un hash
simple no alcanza: el formato `AA#####` tiene pocos millones de valores y
se revierte por fuerza bruta en segundos. Se usa HMAC con `SECRET_KEY`: el
mismo carnet da siempre el mismo seudónimo (se pueden seguir sus eventos),
pero sin la clave no se puede revertir.

Para buscar en los logs los eventos de un carnet concreto:

    docker compose -f docker-compose.prod.yml exec servidor python seudonimo.py AB12345

Si se rota `SECRET_KEY`, los seudónimos cambian a partir de ese momento.

Este módulo no importa nada de la app para poder usarse desde `db/` y como
script sin exigir la conexión a la base de datos."""

import hashlib
import hmac
import os
import sys


def seudonimo(carnet):
    if not carnet:
        return "invitado"
    clave = os.environ.get("SECRET_KEY", "").encode("utf-8")
    digest = hmac.new(clave, str(carnet).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"est-{digest[:12]}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python seudonimo.py <carnet>")
    if not os.environ.get("SECRET_KEY"):
        sys.exit("Falta SECRET_KEY en el entorno (corrélo dentro del contenedor del servidor).")
    print(seudonimo(sys.argv[1].strip().upper()))
