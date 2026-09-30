from datetime import datetime

from .connection import conexion


def obtener_hash(username):
    with conexion() as conn:
        row = conn.execute("SELECT password_hash FROM admins WHERE username = %s", (username,)).fetchone()
        return row["password_hash"] if row else None


def obtener_actualizado(username):
    """Fecha (UTC, ver `actualizar_password`) del último cambio de contraseña de `username`,
    o None si el usuario no existe. La usa `routers/auth.py::verify_token` para rechazar
    JWTs de admin emitidos antes de ese cambio, aunque todavía no hayan expirado."""
    with conexion() as conn:
        row = conn.execute("SELECT actualizado FROM admins WHERE username = %s", (username,)).fetchone()
        return row["actualizado"] if row else None


def actualizar_password(username, nuevo_hash):
    """`actualizado` se fija en UTC calculado acá en Python, no con el `NOW()` de MySQL: así
    queda en el mismo reloj que el `iat` de los JWT (también `datetime.utcnow()`, ver
    `routers/auth.py::create_token`) y la comparación en `verify_token` no depende de qué
    zona horaria tenga configurada el servidor de MySQL."""
    with conexion() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = %s, actualizado = %s WHERE username = %s",
            (nuevo_hash, datetime.utcnow(), username),
        )
        conn.commit()


def revocar_token(jti, expira):
    """Registra el JWT `jti` como revocado hasta `expira` (UTC, el `exp` del propio token).
    Pasada esa fecha el token ya no verifica por sí solo, así que no hace falta guardarlo
    más: se aprovecha cada inserción para purgar las entradas vencidas y que la tabla no
    crezca con cada logout."""
    with conexion() as conn:
        conn.execute("DELETE FROM tokens_revocados WHERE expira < %s", (datetime.utcnow(),))
        conn.execute("INSERT IGNORE INTO tokens_revocados (jti, expira) VALUES (%s, %s)", (jti, expira))
        conn.commit()


def jti_revocado(jti):
    with conexion() as conn:
        row = conn.execute("SELECT 1 FROM tokens_revocados WHERE jti = %s", (jti,)).fetchone()
        return row is not None
