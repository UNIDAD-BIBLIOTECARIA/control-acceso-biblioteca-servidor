from datetime import date, timedelta

from .connection import conexion


def listar_sesiones(fecha=None, pc_id=None, carnet=None, carrera=None, limit=500, offset=0):
    target_date = fecha or date.today().isoformat()

    where_s = ["s.fecha = %s"]
    params_s = [target_date]
    if pc_id:
        where_s.append("s.pc_id = %s")
        params_s.append(pc_id)
    if carnet:
        where_s.append("s.carnet = %s")
        params_s.append(carnet)
    if carrera:
        where_s.append("e.carrera = %s")
        params_s.append(carrera)
    where_sql = "WHERE " + " AND ".join(where_s)

    where_e = [
        "ep.sesion_activa = 1",
        "ep.hora_inicio IS NOT NULL",
        "DATE(ep.hora_inicio) = %s",
        # Si la sesión en curso ya llegó a `sesiones` por /sync (abierta, o ya cerrada
        # y el heartbeat todavía no lo refleja), se muestra solo esa copia.
        "NOT EXISTS (SELECT 1 FROM sesiones sx WHERE sx.pc_id = ep.pc_id AND sx.hora_inicio = ep.hora_inicio)",
    ]
    params_e = [target_date]
    if pc_id:
        where_e.append("ep.pc_id = %s")
        params_e.append(pc_id)
    if carnet:
        where_e.append("ep.carnet = %s")
        params_e.append(carnet)
    if carrera:
        where_e.append("e2.carrera = %s")
        params_e.append(carrera)
    where_estado_sql = "WHERE " + " AND ".join(where_e)

    all_params = params_s + params_e + [limit, offset]

    with conexion() as conn:
        # where_sql/where_estado_sql se arman arriba a partir de una lista fija de
        # comparaciones hardcodeadas (nunca de texto libre): los valores de
        # pc_id/carnet/carrera siempre viajan parametrizados en all_params, nunca
        # interpolados en el string.
        rows = conn.execute(f"""
            SELECT s.id, s.pc_id, s.carnet, s.hora_inicio, s.hora_fin, s.fecha,
                   e.nombre, e.carrera, e.facultad,
                   p.nombre AS pc_nombre, p.ip_reportada AS pc_ip,
                   TIMESTAMPDIFF(MINUTE, s.hora_inicio, COALESCE(s.hora_fin, NOW())) AS minutos
            FROM sesiones s
            LEFT JOIN estudiantes e ON e.carnet = s.carnet
            LEFT JOIN pcs p ON p.pc_id = s.pc_id
            {where_sql}

            UNION ALL

            SELECT
                CONCAT(ep.pc_id, '_', ep.hora_inicio) AS id,
                ep.pc_id,
                ep.carnet,
                ep.hora_inicio,
                NULL AS hora_fin,
                DATE(ep.hora_inicio) AS fecha,
                ep.nombre,
                e2.carrera,
                e2.facultad,
                p2.nombre AS pc_nombre, p2.ip_reportada AS pc_ip,
                TIMESTAMPDIFF(MINUTE, ep.hora_inicio, NOW()) AS minutos
            FROM estado_pcs ep
            LEFT JOIN estudiantes e2 ON e2.carnet = ep.carnet
            LEFT JOIN pcs p2 ON p2.pc_id = ep.pc_id
            {where_estado_sql}

            ORDER BY hora_inicio DESC
            LIMIT %s OFFSET %s
        """, all_params).fetchall()
        return [dict(r) for r in rows]


def pcs_activas():
    with conexion() as conn:
        rows = conn.execute("""
            SELECT pc_id, nombre, ultima_conexion, ip_reportada
            FROM pcs
            WHERE ultima_conexion >= NOW() - INTERVAL 5 MINUTE
            ORDER BY nombre
        """).fetchall()
        return [dict(r) for r in rows]


def resumen_dia(fecha=None):
    target = fecha or date.today().isoformat()
    with conexion() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total_sesiones,
                COUNT(DISTINCT carnet) AS estudiantes_unicos,
                COUNT(DISTINCT pc_id) AS pcs_usadas,
                ROUND(AVG(TIMESTAMPDIFF(MINUTE, hora_inicio, COALESCE(hora_fin, NOW())))) AS minutos_promedio
            FROM (
                SELECT carnet, pc_id, hora_inicio, hora_fin FROM sesiones WHERE fecha = %s
                UNION ALL
                SELECT carnet, pc_id, hora_inicio, NULL AS hora_fin
                FROM estado_pcs
                WHERE sesion_activa = 1 AND hora_inicio IS NOT NULL
                  AND DATE(hora_inicio) = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM sesiones sx WHERE sx.pc_id = estado_pcs.pc_id AND sx.hora_inicio = estado_pcs.hora_inicio
                  )
            ) AS combinadas
        """, (target, target)).fetchone()
        return dict(row)


def estadisticas(desde=None, hasta=None):
    hasta_date = hasta or date.today().isoformat()
    desde_date = desde or (date.today() - timedelta(days=29)).isoformat()

    with conexion() as conn:
        por_dia = conn.execute("""
            SELECT fecha,
                   COUNT(*) AS sesiones,
                   COUNT(DISTINCT carnet) AS estudiantes,
                   ROUND(AVG(TIMESTAMPDIFF(MINUTE, hora_inicio, COALESCE(hora_fin, hora_inicio)))) AS minutos_promedio
            FROM sesiones
            WHERE fecha BETWEEN %s AND %s
            GROUP BY fecha ORDER BY fecha
        """, (desde_date, hasta_date)).fetchall()

        por_hora = conn.execute("""
            SELECT HOUR(hora_inicio) AS hora,
                   COUNT(*) AS sesiones
            FROM sesiones
            WHERE fecha BETWEEN %s AND %s
            GROUP BY hora ORDER BY hora
        """, (desde_date, hasta_date)).fetchall()

        por_carrera = conn.execute("""
            SELECT COALESCE(e.carrera, 'Sin carrera') AS carrera,
                   COUNT(*) AS sesiones,
                   COUNT(DISTINCT s.carnet) AS estudiantes
            FROM sesiones s LEFT JOIN estudiantes e ON e.carnet = s.carnet
            WHERE s.fecha BETWEEN %s AND %s
            GROUP BY carrera ORDER BY sesiones DESC LIMIT 15
        """, (desde_date, hasta_date)).fetchall()

        por_facultad = conn.execute("""
            SELECT COALESCE(e.facultad, 'Sin facultad') AS facultad,
                   COUNT(*) AS sesiones,
                   COUNT(DISTINCT s.carnet) AS estudiantes
            FROM sesiones s LEFT JOIN estudiantes e ON e.carnet = s.carnet
            WHERE s.fecha BETWEEN %s AND %s
            GROUP BY facultad ORDER BY sesiones DESC
        """, (desde_date, hasta_date)).fetchall()

        por_sexo = conn.execute("""
            SELECT COALESCE(e.sexo, 'No especificado') AS sexo,
                   COUNT(*) AS sesiones
            FROM sesiones s LEFT JOIN estudiantes e ON e.carnet = s.carnet
            WHERE s.fecha BETWEEN %s AND %s
            GROUP BY sexo ORDER BY sesiones DESC
        """, (desde_date, hasta_date)).fetchall()

        por_pc = conn.execute("""
            SELECT COALESCE(p.nombre, s.pc_id) AS pc_nombre, COUNT(*) AS sesiones, COUNT(DISTINCT s.carnet) AS estudiantes
            FROM sesiones s
            LEFT JOIN pcs p ON p.pc_id = s.pc_id
            WHERE s.fecha BETWEEN %s AND %s
            GROUP BY s.pc_id, p.nombre ORDER BY sesiones DESC
        """, (desde_date, hasta_date)).fetchall()

        totales = conn.execute("""
            SELECT COUNT(*) AS total_sesiones,
                   COUNT(DISTINCT carnet) AS total_estudiantes,
                   COALESCE(SUM(TIMESTAMPDIFF(MINUTE, hora_inicio, COALESCE(hora_fin, hora_inicio))), 0) AS total_minutos,
                   ROUND(AVG(TIMESTAMPDIFF(MINUTE, hora_inicio, COALESCE(hora_fin, hora_inicio)))) AS minutos_promedio
            FROM sesiones
            WHERE fecha BETWEEN %s AND %s
        """, (desde_date, hasta_date)).fetchone()

        return {
            "desde": desde_date,
            "hasta": hasta_date,
            "totales": dict(totales),
            "por_dia": [dict(r) for r in por_dia],
            "por_hora": [dict(r) for r in por_hora],
            "por_carrera": [dict(r) for r in por_carrera],
            "por_facultad": [dict(r) for r in por_facultad],
            "por_sexo": [dict(r) for r in por_sexo],
            "por_pc": [dict(r) for r in por_pc],
        }
