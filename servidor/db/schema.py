import logging
import os
import re
from datetime import UTC, datetime

from contrasenas_publicadas import es_hash_de_contrasena_publicada

from .connection import conexion

log = logging.getLogger("uvicorn.error")

_HASH_RE = re.compile(r"^pbkdf2_sha256\$\d+\$[0-9a-f]+\$[0-9a-f]+$")

# El ADMIN_PASS_HASH de .env.example es un hash real y
# válido de la contraseña "cambiar-esta-contrasena", publicado en un repo
# público de GitHub. El README y el propio .env.example piden cambiarla
# apenas se entra al panel, pero eso depende de que el operador se acuerde
# de hacerlo — si copia .env.example a .env sin tocar este valor y nunca
# entra a cambiarla, cualquiera que haya visto el repo puede loguearse como
# admin. En vez de confiar solo en el checklist, el propio arranque rechaza
# sembrar el admin inicial con este hash exacto.
_HASH_EJEMPLO_PUBLICO = (
    "pbkdf2_sha256$600000$deec2f9628d2aec504107990557ae826"
    "$716dc1a2a52dc2ce925fc7ca9a369d1d13ef57f23b4105c3e623a5af647e6289"
)


def _tiene_columna(conn, tabla, columna):
    row = conn.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
    """, (tabla, columna)).fetchone()
    return row is not None


def _tipo_columna(conn, tabla, columna):
    row = conn.execute("""
        SELECT data_type AS tipo FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
    """, (tabla, columna)).fetchone()
    return row["tipo"] if row else None


# --- Migraciones versionadas ----------------------------------------------
#
# El CREATE TABLE IF NOT EXISTS de init_db describe siempre el esquema actual completo, así que
# una base nueva ya nace al día. Las migraciones de abajo solo existen para llevar bases creadas
# con versiones anteriores hasta ese mismo esquema. Cada una se aplica una sola vez y queda
# registrada en `schema_migraciones`, en lugar de reevaluarse (o reejecutarse) en cada arranque.
#
# Reglas para agregar una:
#   - Número nuevo al final de MIGRACIONES; nunca renumerar ni editar una ya publicada.
#   - Reflejar el cambio también en el CREATE TABLE de init_db y en db/ESQUEMA.md.
#   - Debe ser idempotente: en MySQL el DDL hace commit implícito, así que no hay rollback
#     transaccional. Si una migración falla a mitad, el arranque aborta sin registrarla y en el
#     siguiente arranque se vuelve a ejecutar desde el estado intermedio en que quedó.
#   - Para deshacer una migración ya aplicada se agrega otra nueva que revierta el cambio
#     (y se restaura un backup si hubo pérdida de datos: hacer backup antes de desplegar).


def _m1_columnas_mantenimiento_y_api_key_en_pcs(conn):
    if not _tiene_columna(conn, "pcs", "ultimo_mantenimiento"):
        conn.execute("ALTER TABLE pcs ADD COLUMN ultimo_mantenimiento DATETIME NULL")
    if not _tiene_columna(conn, "pcs", "api_key_hash"):
        conn.execute("ALTER TABLE pcs ADD COLUMN api_key_hash VARCHAR(255) NULL")
    if not _tiene_columna(conn, "pcs", "api_key_generada"):
        conn.execute("ALTER TABLE pcs ADD COLUMN api_key_generada DATETIME NULL")


def _m2_carnet_de_sesion_opcional(conn):
    conn.execute("ALTER TABLE sesiones MODIFY COLUMN carnet VARCHAR(30) NULL")


def _m3_quitar_departamento_de_estudiantes(conn):
    if _tiene_columna(conn, "estudiantes", "departamento"):
        conn.execute("ALTER TABLE estudiantes DROP COLUMN departamento")


def _m4_fecha_nacimiento_como_anio(conn):
    """El kiosko solo captura el año de nacimiento. Un ALTER MODIFY directo de DATE a YEAR no
    extrae el año (MySQL lo trunca a 0000), así que se pasa por una columna auxiliar. Cada paso
    comprueba el estado para poder retomarse si un arranque anterior se cortó a mitad."""
    if _tipo_columna(conn, "estudiantes", "fecha_nacimiento") == "date":
        if not _tiene_columna(conn, "estudiantes", "fecha_nacimiento_new"):
            conn.execute("ALTER TABLE estudiantes ADD COLUMN fecha_nacimiento_new YEAR")
        conn.execute(
            "UPDATE estudiantes SET fecha_nacimiento_new = YEAR(fecha_nacimiento) "
            "WHERE fecha_nacimiento IS NOT NULL"
        )
        conn.commit()
        conn.execute("ALTER TABLE estudiantes DROP COLUMN fecha_nacimiento")
    if _tiene_columna(conn, "estudiantes", "fecha_nacimiento_new"):
        conn.execute("ALTER TABLE estudiantes CHANGE COLUMN fecha_nacimiento_new fecha_nacimiento YEAR")


MIGRACIONES = [
    (1, "columnas de mantenimiento y API key en pcs", _m1_columnas_mantenimiento_y_api_key_en_pcs),
    (2, "sesiones.carnet admite NULL", _m2_carnet_de_sesion_opcional),
    (3, "quitar estudiantes.departamento", _m3_quitar_departamento_de_estudiantes),
    (4, "estudiantes.fecha_nacimiento de DATE a YEAR", _m4_fecha_nacimiento_como_anio),
]


def _aplicar_migraciones(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migraciones (
            version INT PRIMARY KEY,
            descripcion VARCHAR(255) NOT NULL,
            aplicada DATETIME NOT NULL
        ) ENGINE=InnoDB
    """)
    # Un lock con nombre evita que dos procesos arrancando a la vez apliquen la misma migración.
    if conn.execute("SELECT GET_LOCK('biblioteca_migraciones', 60) AS ok").fetchone()["ok"] != 1:
        raise RuntimeError("No se pudo obtener el lock de migraciones (¿otro proceso migrando?)")
    try:
        aplicadas = {row["version"] for row in conn.execute("SELECT version FROM schema_migraciones").fetchall()}
        for version, descripcion, migrar in MIGRACIONES:
            if version in aplicadas:
                continue
            log.info("Aplicando migración %d: %s", version, descripcion)
            migrar(conn)
            conn.execute(
                "INSERT INTO schema_migraciones (version, descripcion, aplicada) VALUES (%s, %s, %s)",
                (version, descripcion, datetime.now(UTC).replace(tzinfo=None)),
            )
            conn.commit()
    finally:
        conn.execute("SELECT RELEASE_LOCK('biblioteca_migraciones')")


def init_db():
    with conexion() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS estudiantes (
                carnet VARCHAR(30) PRIMARY KEY,
                nombre VARCHAR(255),
                fecha_nacimiento YEAR,
                carrera VARCHAR(255),
                facultad VARCHAR(255),
                sexo VARCHAR(20),
                fecha_registro DATE NOT NULL
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS pcs (
                pc_id VARCHAR(100) PRIMARY KEY,
                nombre VARCHAR(255),
                ultima_conexion DATETIME,
                ip_reportada VARCHAR(45),
                ultimo_mantenimiento DATETIME,
                api_key_hash VARCHAR(255),
                api_key_generada DATETIME
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS sesiones (
                id VARCHAR(100) PRIMARY KEY,
                pc_id VARCHAR(100) NOT NULL,
                carnet VARCHAR(30),
                hora_inicio DATETIME NOT NULL,
                hora_fin DATETIME,
                fecha DATE NOT NULL,
                sincronizado TINYINT(1) DEFAULT 0,
                timestamp_sync DATETIME,
                INDEX idx_sesiones_fecha (fecha),
                INDEX idx_sesiones_carnet (carnet),
                INDEX idx_sesiones_pc_id (pc_id),
                CONSTRAINT fk_sesiones_pc FOREIGN KEY (pc_id) REFERENCES pcs(pc_id),
                CONSTRAINT fk_sesiones_estudiante FOREIGN KEY (carnet) REFERENCES estudiantes(carnet)
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS estado_pcs (
                pc_id VARCHAR(100) PRIMARY KEY,
                pc_nombre VARCHAR(255),
                sesion_activa TINYINT(1) DEFAULT 0,
                carnet VARCHAR(30),
                nombre VARCHAR(255),
                hora_inicio DATETIME,
                ultima_actualizacion DATETIME,
                CONSTRAINT fk_estado_pcs_pc FOREIGN KEY (pc_id) REFERENCES pcs(pc_id),
                CONSTRAINT fk_estado_pcs_estudiante FOREIGN KEY (carnet) REFERENCES estudiantes(carnet) ON DELETE SET NULL
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS admins (
                username VARCHAR(100) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                actualizado DATETIME
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS pcs_hardware (
                pc_id VARCHAR(100) PRIMARY KEY,
                hostname VARCHAR(255),
                mac_address VARCHAR(20),
                cpu VARCHAR(255),
                ram_total_mb INT,
                almacenamiento_total_gb INT,
                sistema_operativo VARCHAR(255),
                temperatura_cpu_c DECIMAL(5,1),
                disco_smart_ok TINYINT(1),
                horas_uso_acumuladas DECIMAL(8,2) NOT NULL DEFAULT 0,
                ultima_lectura DATETIME,
                CONSTRAINT fk_pcs_hardware_pc FOREIGN KEY (pc_id) REFERENCES pcs(pc_id)
            ) ENGINE=InnoDB;

            CREATE TABLE IF NOT EXISTS tokens_revocados (
                jti VARCHAR(64) PRIMARY KEY,
                expira DATETIME NOT NULL,
                INDEX idx_tokens_revocados_expira (expira)
            ) ENGINE=InnoDB;
        """)
        conn.commit()

        _aplicar_migraciones(conn)

        _sembrar_admin_inicial(conn)


def _sembrar_admin_inicial(conn):
    """Crea el primer administrador si la tabla `admins` está vacía, usando
    `ADMIN_USER`/`ADMIN_PASS_HASH` del entorno como valor de arranque único.

    A partir de acá las credenciales viven en la base de datos, no en el
    `.env`: el panel expone `PUT /auth/password` para que el propio
    administrador las cambie después de este primer login — así quien
    despliega la app puede fijar unas credenciales iniciales sin que sean
    las que se usan a largo plazo."""
    if conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        return

    username = os.environ.get("ADMIN_USER", "")
    password_hash = os.environ.get("ADMIN_PASS_HASH", "")
    if not username or not password_hash:
        log.warning(
            "No hay administradores en la base de datos y ADMIN_USER/ADMIN_PASS_HASH "
            "no están configurados en el .env: nadie podrá iniciar sesión en el panel "
            "hasta que se inserte un admin manualmente o se configuren esas variables "
            "y se reinicie el servidor."
        )
        return
    if not _HASH_RE.match(password_hash):
        log.warning(
            "ADMIN_PASS_HASH no tiene el formato esperado (pbkdf2_sha256$...); "
            "generalo con 'python3 servidor/generar_hash_admin.py'. No se creó el "
            "administrador inicial."
        )
        return
    if password_hash == _HASH_EJEMPLO_PUBLICO:
        log.error(
            "ADMIN_PASS_HASH es el hash de ejemplo de .env.example (contraseña "
            "'cambiar-esta-contrasena'), publicado en un repo público de GitHub — "
            "no se creó el administrador inicial. Generá tu propio hash con "
            "'python3 servidor/generar_hash_admin.py' y fijalo en el .env real."
        )
        return
    if es_hash_de_contrasena_publicada(password_hash):
        log.error(
            "ADMIN_PASS_HASH corresponde a una contraseña que ya se publicó en el historial "
            "del repo público — no se creó el administrador inicial. Generá un hash de una "
            "contraseña nueva con 'python3 servidor/generar_hash_admin.py'."
        )
        return

    conn.execute(
        "INSERT INTO admins (username, password_hash, actualizado) VALUES (%s, %s, %s)",
        (username, password_hash, datetime.now(UTC).replace(tzinfo=None)),
    )
    conn.commit()
    log.info("Administrador inicial '%s' creado a partir de ADMIN_USER/ADMIN_PASS_HASH.", username)
