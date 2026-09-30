import os
import sys
from pathlib import Path

import pytest

# Los módulos de la app (routers, db, models) se importan como paquetes de
# nivel superior (`from routers import auth`, no `from servidor.routers...`),
# así que hace falta el directorio `servidor/` en sys.path — igual que
# cuando corre main.py con `servidor/` como cwd (ver Dockerfile/uvicorn).
SERVIDOR_DIR = Path(__file__).resolve().parents[1]
if str(SERVIDOR_DIR) not in sys.path:
    sys.path.insert(0, str(SERVIDOR_DIR))

# routers/auth.py exige SECRET_KEY al importarse (`_require_env`) y falla con
# RuntimeError si falta. Se fija acá, antes de que cualquier test importe el
# módulo, para no depender de un .env real ni de variables de entorno puestas
# a mano al correr pytest.
os.environ.setdefault("SECRET_KEY", "clave-de-prueba-solo-para-tests-no-usar-en-produccion")

# db/connection.py exige DB_USER y DB_PASSWORD al importarse (mismo patrón
# `_require_env` que SECRET_KEY, ver arriba) y `db/__init__.py` importa
# `connection` en cadena, así que hasta los tests que no tocan MySQL
# (test_auth.py, test_umbrales.py) disparan esa validación solo con
# `from routers import auth` / `from db import ...`. Se fijan acá por el
# mismo motivo que SECRET_KEY: no depender de un .env real ni de variables
# puestas a mano al correr pytest. Ningún test abre una conexión real a
# MySQL con estos valores.
os.environ.setdefault("DB_USER", "usuario-de-prueba-solo-para-tests")
os.environ.setdefault("DB_PASSWORD", "clave-de-prueba-solo-para-tests")


@pytest.fixture(autouse=True)
def _limpiar_contadores_de_rate_limiting():
    """`_intentos_fallidos`, `_lecturas_estudiante` y `_escrituras_kiosko` (ver
    routers/auth.py) viven en dicts a nivel de módulo, no por-test — sin este
    fixture, el orden en que corren los tests de rate limiting (y cualquier
    otro test que dispare login/limitar_*) contaminaría los contadores de los
    demás. Se aplica a toda la suite (autouse) aunque hoy solo lo necesiten
    test_rate_limiting.py y test_endpoints.py, para que un test nuevo en otro
    archivo no vuelva a abrir este mismo problema."""
    from routers import auth
    auth._intentos_fallidos.clear()
    auth._lecturas_estudiante.clear()
    auth._escrituras_kiosko.clear()
    yield
    auth._intentos_fallidos.clear()
    auth._lecturas_estudiante.clear()
    auth._escrituras_kiosko.clear()


@pytest.fixture(autouse=True)
def tokens_revocados(monkeypatch):
    """Doble en memoria de la tabla `tokens_revocados`: `verify_token` consulta
    `db_admins.jti_revocado` en cada JWT de admin y `POST /auth/logout` llama a
    `db_admins.revocar_token`, así que sin esto cualquier test que autentique
    como admin o cierre sesión abriría una conexión real a MySQL. Devuelve el
    set de `jti` revocados para que un test pueda inspeccionarlo."""
    from db import admins as db_admins
    revocados = set()
    monkeypatch.setattr(db_admins, "jti_revocado", lambda jti: jti in revocados)
    monkeypatch.setattr(db_admins, "revocar_token", lambda jti, expira: revocados.add(jti))
    return revocados
