import os
from contextlib import contextmanager

import pymysql
import pymysql.cursors
from contrasenas_publicadas import es_contrasena_publicada


def _require_env(name: str) -> str:
    """Mismo criterio que `routers/auth.py` para `SECRET_KEY`: si falta la variable, el proceso
    debe fallar de forma ruidosa al arrancar en vez de conectar con una credencial adivinable."""
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(
            f"La variable de entorno {name} es obligatoria y no puede estar vacía. "
            f"Configúrala en tu .env antes de iniciar el servidor."
        )
    return value


DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = _require_env("DB_USER")
DB_PASSWORD = _require_env("DB_PASSWORD")
if es_contrasena_publicada(DB_PASSWORD):
    raise RuntimeError(
        "DB_PASSWORD es una contraseña que ya se publicó en el historial del repo público y "
        "debe considerarse conocida. Fija una nueva (p. ej. `openssl rand -hex 24`) en el .env "
        "y cámbiala también en MySQL antes de iniciar el servidor."
    )
DB_NAME = os.environ.get("DB_NAME", "biblioteca")

# Ruta (dentro del contenedor) a un certificado CA para cifrar la conexión a
# MySQL. Vacío = conexión en texto plano, sin impacto mientras "db" y
# "servidor" compartan la red interna de Docker (caso por defecto de este
# repo). Solo hace falta fijarla si la base de datos se aloja fuera de esa
# red (managed DB en la nube, otra máquina): apuntarla al CA cert que dé el
# proveedor de la base de datos.
DB_SSL_CA = os.environ.get("DB_SSL_CA") or None

# Sin timeouts, PyMySQL espera indefinidamente a un MySQL colgado (no caído:
# el socket sigue abierto pero no responde) y cada request atrapado ocupa un
# hilo del threadpool de FastAPI hasta agotarlo. Con ellos, la consulta falla
# con un 500 en segundos y el hilo se libera.
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT") or 5)
DB_READ_TIMEOUT = int(os.environ.get("DB_READ_TIMEOUT") or 10)
DB_WRITE_TIMEOUT = int(os.environ.get("DB_WRITE_TIMEOUT") or 10)


class ConnectionWrapper:
    """Envuelve la conexion de pymysql para exponer conn.execute(), como sqlite3."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        return cursor

    def executescript(self, script):
        cursor = self._conn.cursor()
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection(connect_timeout=None, read_timeout=None, write_timeout=None):
    ssl_args = {"ssl_ca": DB_SSL_CA, "ssl_verify_cert": True} if DB_SSL_CA else {}
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=connect_timeout or DB_CONNECT_TIMEOUT,
        read_timeout=read_timeout or DB_READ_TIMEOUT,
        write_timeout=write_timeout or DB_WRITE_TIMEOUT,
        **ssl_args,
    )
    return ConnectionWrapper(conn)


def ping(timeout=2):
    """`SELECT 1` con timeouts cortos, para `/health/ready`. Lanza excepción si
    MySQL no responde a tiempo; tiene que caber dentro del `--timeout` del
    HEALTHCHECK del Dockerfile."""
    conn = get_connection(connect_timeout=timeout, read_timeout=timeout, write_timeout=timeout)
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()


@contextmanager
def conexion():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
