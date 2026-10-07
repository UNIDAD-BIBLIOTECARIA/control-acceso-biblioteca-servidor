import re
from datetime import UTC, datetime

import pymysql

from .connection import conexion


class CarnetYaRegistrado(Exception):
    pass


class EstudianteNoEncontrado(Exception):
    pass


class TieneSesionesRegistradas(Exception):
    pass


def _normalizar_fecha_nacimiento(valor):
    """Solo se captura el año de nacimiento. Cualquier valor que no traiga
    un año de 4 dígitos dentro del rango de la columna YEAR (1901-2155) se
    guarda como NULL en vez de dejar que MySQL truene con DataError."""
    if valor is None:
        return None
    match = re.match(r"(\d{4})", str(valor))
    if not match:
        return None
    anio = int(match.group(1))
    if not (1901 <= anio <= 2155):
        return None
    return anio


def crear(est):
    with conexion() as conn:
        existe = conn.execute("SELECT carnet FROM estudiantes WHERE carnet = %s", (est.carnet,)).fetchone()
        if existe:
            raise CarnetYaRegistrado()

        fecha_reg = est.fecha_registro or datetime.now(UTC).date().isoformat()
        conn.execute("""
            INSERT INTO estudiantes (carnet, nombre, fecha_nacimiento, carrera, facultad, sexo, fecha_registro)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (est.carnet, est.nombre, _normalizar_fecha_nacimiento(est.fecha_nacimiento), est.carrera, est.facultad, est.sexo, fecha_reg))
        conn.commit()


def listar():
    with conexion() as conn:
        rows = conn.execute("SELECT * FROM estudiantes ORDER BY nombre IS NULL, nombre").fetchall()
        return [dict(r) for r in rows]


def obtener(carnet):
    with conexion() as conn:
        row = conn.execute("SELECT * FROM estudiantes WHERE carnet = %s", (carnet,)).fetchone()
        if not row:
            raise EstudianteNoEncontrado()
        return dict(row)


def actualizar(carnet, est):
    with conexion() as conn:
        existe = conn.execute("SELECT carnet FROM estudiantes WHERE carnet = %s", (carnet,)).fetchone()
        if not existe:
            raise EstudianteNoEncontrado()
        conn.execute("""
            UPDATE estudiantes
            SET nombre=%s, fecha_nacimiento=%s, carrera=%s, facultad=%s, sexo=%s
            WHERE carnet=%s
        """, (est.nombre, _normalizar_fecha_nacimiento(est.fecha_nacimiento), est.carrera, est.facultad, est.sexo, carnet))
        conn.commit()


def eliminar(carnet):
    with conexion() as conn:
        existe = conn.execute("SELECT carnet FROM estudiantes WHERE carnet = %s", (carnet,)).fetchone()
        if not existe:
            raise EstudianteNoEncontrado()
        try:
            conn.execute("DELETE FROM estudiantes WHERE carnet = %s", (carnet,))
            conn.commit()
        except pymysql.err.IntegrityError:
            raise TieneSesionesRegistradas() from None


def asegurar_desde_sesion(conn, carnet, nombre, carrera, facultad, sexo, fecha_nacimiento, fecha_registro):
    """Crea el estudiante si todavía no existe, para que la sesión cumpla la FK.
    Nunca modifica una ficha existente: /sync y /estado aceptan cientos de
    carnets por minuto con la key de un kiosko, así que si pudieran editar
    datos, una key filtrada bastaría para reescribir en masa a toda la
    población estudiantil. Editar es trabajo de PUT /estudiantes/{carnet},
    que tiene rate limit por request.

    Se usa `ON DUPLICATE KEY UPDATE carnet = carnet` en vez de INSERT IGNORE
    para no convertir en warnings otros errores (datos truncados, etc.). El
    rowcount del cursor queda en 1 si se creó la ficha y en 0 si ya existía."""
    conn.execute("""
        INSERT INTO estudiantes (carnet, nombre, carrera, facultad, sexo, fecha_nacimiento, fecha_registro)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE carnet = carnet
    """, (carnet, nombre, carrera, facultad, sexo, _normalizar_fecha_nacimiento(fecha_nacimiento), fecha_registro))
