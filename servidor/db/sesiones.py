import logging
from datetime import datetime

from seudonimo import seudonimo

from . import pcs as db_pcs
from .connection import conexion
from .estudiantes import asegurar_desde_sesion

log = logging.getLogger("uvicorn.error")


def registrar_sync(payload, ip):
    with conexion() as conn:
        cursor = conn.cursor()
        ahora = datetime.now().isoformat()

        db_pcs.upsert_conexion(cursor, payload.pc_id, payload.pc_nombre, ahora, ip)

        insertados = 0
        estudiantes_creados = 0
        fecha_hoy = datetime.now().date().isoformat()
        for s in payload.sesiones:
            if s.carnet:
                try:
                    asegurar_desde_sesion(
                        cursor, s.carnet, s.nombre, s.carrera, s.facultad,
                        s.sexo, s.fecha_nacimiento, fecha_hoy,
                    )
                    if cursor.rowcount > 0:
                        estudiantes_creados += 1
                except Exception:
                    log.exception(
                        "No se pudo crear el estudiante %s durante sync — "
                        "se registra la sesión igual", seudonimo(s.carnet),
                    )

            cursor.execute("""
                INSERT INTO sesiones
                    (id, pc_id, carnet, hora_inicio, hora_fin, fecha, sincronizado, timestamp_sync)
                VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
                ON DUPLICATE KEY UPDATE
                    -- Si el id ya existe pero pertenece a otra PC, no se toca:
                    -- una PC no puede cerrar ni alterar sesiones ajenas.
                    hora_fin       = IF(pc_id = VALUES(pc_id) AND VALUES(hora_fin) IS NOT NULL, VALUES(hora_fin), hora_fin),
                    sincronizado   = IF(pc_id = VALUES(pc_id) AND VALUES(hora_fin) IS NOT NULL, 1, sincronizado),
                    timestamp_sync = IF(pc_id = VALUES(pc_id) AND VALUES(hora_fin) IS NOT NULL, VALUES(timestamp_sync), timestamp_sync)
            """, (s.id, s.pc_id, s.carnet, s.hora_inicio, s.hora_fin, s.fecha, ahora))
            if cursor.rowcount > 0:
                insertados += 1

        conn.commit()
        return {
            "recibidos": len(payload.sesiones),
            "insertados": insertados,
            "estudiantes_creados": estudiantes_creados,
            "timestamp": ahora,
        }
