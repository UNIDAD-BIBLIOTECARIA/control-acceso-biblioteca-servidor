from datetime import datetime

from .connection import conexion
from .umbrales import calcular_estado


def upsert_conexion(conn, pc_id, nombre, ultima_conexion, ip):
    """Marca que la PC se comunicó con el servidor (lo usan /sync y el heartbeat
    de /estado). `ultima_conexion` es lo que mira /reportes/pcs-activas. Un
    nombre o IP ausentes en el payload no borran los que ya había."""
    conn.execute("""
        INSERT INTO pcs (pc_id, nombre, ultima_conexion, ip_reportada)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            nombre = COALESCE(VALUES(nombre), nombre),
            ultima_conexion = VALUES(ultima_conexion),
            ip_reportada = COALESCE(VALUES(ip_reportada), ip_reportada)
    """, (pc_id, nombre, ultima_conexion, ip))


def asegurar(conn, pc_id, nombre):
    conn.execute("""
        INSERT INTO pcs (pc_id, nombre)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            nombre = COALESCE(VALUES(nombre), nombre)
    """, (pc_id, nombre))


def fijar_api_key(pc_id, api_key_hash):
    """Guarda el hash de una API key nueva/rotada para `pc_id` (crea la fila
    en `pcs` si la PC todavía no se había conectado nunca). Solo se persiste
    el hash — la key en texto plano no se guarda en ningún lado, igual que
    las contraseñas de admin; si se pierde, la única opción es rotarla."""
    with conexion() as conn:
        asegurar(conn, pc_id, None)
        conn.execute(
            "UPDATE pcs SET api_key_hash = %s, api_key_generada = %s WHERE pc_id = %s",
            (api_key_hash, datetime.now().isoformat(), pc_id),
        )
        conn.commit()


def revocar_api_key(pc_id) -> bool:
    """Invalida la API key de una sola PC sin afectar a las demás ni borrar
    su historial (`pcs`/`sesiones` siguen intactos). Devuelve False si la
    PC no existe."""
    with conexion() as conn:
        cursor = conn.execute(
            "UPDATE pcs SET api_key_hash = NULL WHERE pc_id = %s", (pc_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


def obtener_api_key_hash(pc_id):
    with conexion() as conn:
        row = conn.execute(
            "SELECT api_key_hash FROM pcs WHERE pc_id = %s", (pc_id,)
        ).fetchone()
        return row["api_key_hash"] if row else None


def registrar_mantenimiento(pc_id):
    with conexion() as conn:
        cursor = conn.execute(
            "UPDATE pcs SET ultimo_mantenimiento = %s WHERE pc_id = %s",
            (datetime.now().isoformat(), pc_id),
        )
        # El agente de hardware del cliente resetea su acumulador local al
        # detectar un nuevo ultimo_mantenimiento, pero eso solo se refleja
        # aquí en el próximo heartbeat. Reseteamos ya mismo el valor
        # guardado para que estado_mantenimiento vuelva a "optimo" de
        # inmediato en vez de quedarse en "critico"/"pendiente" hasta esa
        # siguiente lectura.
        conn.execute(
            "UPDATE pcs_hardware SET horas_uso_acumuladas = 0 WHERE pc_id = %s",
            (pc_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def listar_mantenimiento():
    """PCs con su fecha de último mantenimiento, el tiempo de uso (suma de
    duraciones de sesiones) acumulado desde entonces, y la última lectura
    del agente de hardware del cliente (specs, salud, horas reales de
    encendido), como referencia para saber a cuáles les toca mantenimiento.

    minutos_uso_desde_mantenimiento: tiempo de sesiones de estudiantes/invitados.
    horas_uso_acumuladas / estado_mantenimiento: tiempo real que la PC estuvo
    encendida desde el último mantenimiento (base de las alertas de
    300h/400h), reportado por el agente de hardware del cliente."""
    with conexion() as conn:
        rows = conn.execute("""
            SELECT p.pc_id, p.nombre, p.ultima_conexion, p.ultimo_mantenimiento,
                   (p.api_key_hash IS NOT NULL) AS tiene_api_key,
                   COALESCE(SUM(TIMESTAMPDIFF(MINUTE, t.hora_inicio, COALESCE(t.hora_fin, NOW()))), 0)
                       AS minutos_uso_desde_mantenimiento,
                   h.hostname, h.mac_address, h.cpu, h.ram_total_mb, h.almacenamiento_total_gb,
                   h.sistema_operativo, h.temperatura_cpu_c, h.disco_smart_ok,
                   h.horas_uso_acumuladas, h.ultima_lectura
            FROM pcs p
            LEFT JOIN (
                SELECT pc_id, hora_inicio, hora_fin FROM sesiones
                UNION ALL
                SELECT pc_id, hora_inicio, NULL AS hora_fin
                FROM estado_pcs
                WHERE sesion_activa = 1 AND hora_inicio IS NOT NULL
                  -- Misma deduplicación que db/reportes.py: si la sesión en curso
                  -- ya llegó a `sesiones` por /sync, no se cuenta dos veces.
                  AND NOT EXISTS (
                      SELECT 1 FROM sesiones sx
                      WHERE sx.pc_id = estado_pcs.pc_id AND sx.hora_inicio = estado_pcs.hora_inicio
                  )
            ) t ON t.pc_id = p.pc_id
               AND t.hora_inicio >= COALESCE(p.ultimo_mantenimiento, '1970-01-01 00:00:00')
            LEFT JOIN pcs_hardware h ON h.pc_id = p.pc_id
            GROUP BY p.pc_id, p.nombre, p.ultima_conexion, p.ultimo_mantenimiento, p.api_key_hash,
                     h.hostname, h.mac_address, h.cpu, h.ram_total_mb, h.almacenamiento_total_gb,
                     h.sistema_operativo, h.temperatura_cpu_c, h.disco_smart_ok,
                     h.horas_uso_acumuladas, h.ultima_lectura
            ORDER BY p.nombre
        """).fetchall()
        resultado = []
        for r in rows:
            d = dict(r)
            d["estado_mantenimiento"] = calcular_estado(d["horas_uso_acumuladas"])
            resultado.append(d)
        return resultado
