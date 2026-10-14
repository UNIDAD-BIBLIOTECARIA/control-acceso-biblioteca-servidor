from datetime import datetime

from . import pcs as db_pcs
from .connection import conexion
from .estudiantes import asegurar_desde_sesion
from .umbrales import UMBRAL_DISPONIBLE_MINUTOS


def actualizar_estado(payload, ip=None):
    with conexion() as conn:
        ahora = datetime.now().isoformat()

        # El heartbeat llega cada ~30s haya o no sesión, a diferencia de /sync
        # (solo cuando hay sesiones cerradas que enviar): es lo que mantiene al
        # día `pcs.ultima_conexion` para el indicador de PCs activas.
        db_pcs.upsert_conexion(conn, payload.pc_id, payload.pc_nombre, ahora, ip)

        if payload.carnet:
            fecha_hoy = datetime.now().date().isoformat()
            asegurar_desde_sesion(
                conn, payload.carnet, payload.nombre, payload.carrera,
                payload.facultad, payload.sexo,
                payload.fecha_nacimiento, fecha_hoy,
            )

        conn.execute("""
            INSERT INTO estado_pcs (pc_id, pc_nombre, sesion_activa, carnet, nombre, hora_inicio, ultima_actualizacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                pc_nombre            = VALUES(pc_nombre),
                sesion_activa        = VALUES(sesion_activa),
                carnet               = VALUES(carnet),
                nombre               = VALUES(nombre),
                hora_inicio          = VALUES(hora_inicio),
                ultima_actualizacion = VALUES(ultima_actualizacion)
        """, (
            payload.pc_id,
            payload.pc_nombre,
            int(payload.sesion_activa),
            payload.carnet,
            payload.nombre,
            payload.hora_inicio,
            ahora,
        ))

        conn.commit()
        return ahora


def carnet_activo_en_pc(pc_id: str, carnet: str) -> bool:
    """True si `carnet` es el de la sesión abierta en `pc_id` según el último
    heartbeat de esa PC (POST /estado)."""
    with conexion() as conn:
        row = conn.execute(
            "SELECT 1 FROM estado_pcs WHERE pc_id = %s AND sesion_activa = 1 AND carnet = %s",
            (pc_id, carnet),
        ).fetchone()
        return row is not None


def listar_estados():
    with conexion() as conn:
        rows = conn.execute(f"""
            SELECT *,
                CASE
                    WHEN sesion_activa = 1 THEN 'en_uso'
                    WHEN ultima_actualizacion >= NOW() - INTERVAL {UMBRAL_DISPONIBLE_MINUTOS} MINUTE THEN 'disponible'
                    ELSE 'no_disponible'
                END AS estado_pc
            FROM estado_pcs
            ORDER BY pc_nombre
        """).fetchall()
        return [dict(r) for r in rows]
