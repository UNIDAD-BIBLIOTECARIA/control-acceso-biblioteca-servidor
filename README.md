# Biblioteca Servidor

Backend de control de acceso y gestión para una sala de PCs / biblioteca universitaria (Universidad de El Salvador, Facultad Multidisciplinaria de Oriente). Es la mitad "servidor" de un sistema cliente-servidor: cada PC de la sala corre una app de escritorio (kiosko, proyecto hermano `biblioteca_cliente`) que se autentica con el carnet del estudiante, registra el tiempo de uso y reporta telemetría de hardware; este backend centraliza esa información, la sincroniza de forma offline-first y expone un panel web de administración.

## Qué problema resuelve

- Saber **qué estudiante usa qué PC y durante cuánto tiempo**, incluyendo un modo "invitado" para personal no estudiantil (administrativo, docente, visitante) sin carnet.
- Permitir que los kioscos de cada PC funcionen **sin conexión continua**: acumulan sesiones localmente y las sincronizan por lotes cuando hay red (`/sync`).
- Mostrar en **tiempo real** qué PCs están libres o en uso (`/estado`).
- Recibir **telemetría de hardware** (specs, temperatura, salud de disco, horas de encendido) de cada PC para anticipar mantenimiento preventivo.
- Generar **reportes y estadísticas** de uso (por día, hora, carrera, facultad, sexo, PC) para la administración académica.
- Servir un **panel web** de administración para todo lo anterior.

## Arquitectura y stack

- **FastAPI** + **Pydantic** sobre **Uvicorn** (ASGI).
- **MySQL 8.4** como motor de base de datos, accedido con **SQL crudo** vía `PyMySQL` (sin ORM).
- **JWT** (`PyJWT`) para el login del panel administrativo.
- **Docker Compose** para orquestar servidor + base de datos.
- **Panel web**: HTML/CSS/JS vanilla sin build step, con **Chart.js** cargado desde CDN solo en la vista de estadísticas.

Dependencias (`servidor/requirements.txt`): `fastapi`, `uvicorn[standard]`, `pydantic`, `PyJWT`, `PyMySQL`, `prometheus-client`. Requiere **Python 3.11+** (la imagen Docker usa 3.12).

### Estructura de carpetas

```
servidor/
├── main.py               # entry point: registra routers, CORS, monta el panel, /health
├── db/                    # acceso a datos (SQL crudo vía PyMySQL)
│   ├── connection.py       # ConnectionWrapper: envuelve PyMySQL con API estilo sqlite3
│   ├── schema.py            # DDL de todas las tablas + migraciones versionadas
│   ├── ESQUEMA.md            # diagrama ER y detalle de cada tabla
│   ├── estudiantes.py, pcs.py, sesiones.py, estado.py, hardware.py, reportes.py, umbrales.py, admins.py
├── models/                # esquemas Pydantic de entrada/salida (catalogo.py: facultades y carreras válidas)
├── routers/               # endpoints FastAPI, uno por dominio
├── panel/                 # SPA estática (HTML/CSS/JS) servida en /panel y /
├── scripts/               # backup/restore de MySQL, CA interna y certificados TLS
├── tests/                 # pytest (sin MySQL real: la capa db se reemplaza por dobles)
├── Dockerfile, docker-entrypoint.sh, healthcheck.py
└── requirements.txt
```

## Modelo de datos

Definido en `servidor/db/schema.py` (`init_db()`), todas las tablas en `ENGINE=InnoDB`:

| Tabla | Campos principales | Notas |
|---|---|---|
| `estudiantes` | `carnet` (PK), `nombre`, `fecha_nacimiento` (**solo año**, tipo `YEAR`), `carrera`, `facultad`, `sexo`, `fecha_registro` | El kiosko solo captura el año de nacimiento, no la fecha completa |
| `pcs` | `pc_id` (PK), `nombre`, `ultima_conexion`, `ip_reportada`, `ultimo_mantenimiento`, `api_key_hash`, `api_key_generada` | Identidad estable de cada PC física y hash de su API key |
| `sesiones` | `id` (PK, **generado por el cliente**), `pc_id` (FK), `carnet` (FK, **nullable** → modo invitado), `hora_inicio`, `hora_fin` (NULL = sesión en curso), `fecha`, `sincronizado`, `timestamp_sync` | Registro histórico autoritativo de uso. Índices en `fecha`, `carnet`, `pc_id` |
| `estado_pcs` | `pc_id` (PK/FK), `pc_nombre`, `sesion_activa`, `carnet` (FK, `ON DELETE SET NULL`), `nombre`, `hora_inicio`, `ultima_actualizacion` | Snapshot en vivo (1 fila por PC, sobrescrita en cada heartbeat) |
| `pcs_hardware` | `pc_id` (PK/FK), `hostname`, `mac_address`, `cpu`, `ram_total_mb`, `almacenamiento_total_gb`, `sistema_operativo`, `temperatura_cpu_c`, `disco_smart_ok`, `horas_uso_acumuladas`, `ultima_lectura` | Telemetría reportada por el agente de hardware del cliente |
| `admins` | `username` (PK), `password_hash`, `actualizado` | Administradores del panel (ver Seguridad) |
| `tokens_revocados` | `jti` (PK), `expira` | JWT dados de baja por `POST /auth/logout` hasta que expiran |
| `schema_migraciones` | `version` (PK), `descripcion`, `aplicada` | Migraciones de esquema ya aplicadas |

`sesiones` no tiene `ON DELETE` en su FK a `estudiantes`, por lo que borrar un estudiante con sesiones asociadas falla con conflicto (ver endpoint `DELETE /estudiantes/{carnet}`).

No se usa Alembic: una base nueva nace con el esquema completo desde los `CREATE TABLE IF NOT EXISTS` de `init_db()`, y las bases creadas con versiones anteriores se ponen al día con las migraciones versionadas de `MIGRACIONES` (`db/schema.py`). Cada una se aplica **una sola vez** al arrancar y queda registrada en `schema_migraciones`; son idempotentes porque el DDL de MySQL no es transaccional. Las actuales:
1. Añadir `pcs.ultimo_mantenimiento`, `pcs.api_key_hash` y `pcs.api_key_generada` si faltan.
2. Volver `sesiones.carnet` nullable (para soportar el modo invitado).
3. Eliminar la vieja columna `estudiantes.departamento`.
4. Convertir `estudiantes.fecha_nacimiento` de `DATE` a `YEAR` pasando por una columna temporal (un `ALTER MODIFY` directo trunca a `0000` en MySQL).

Hacer un backup (`servidor/scripts/backup_db.sh`) antes de desplegar una versión que agregue migraciones.

## Endpoints de la API

Tres niveles de acceso:

- **pública** — sin credenciales.
- **🔒 admin** — JWT de administrador, por `Authorization: Bearer <token>` (scripts/API) o por la cookie `access_token` que setea `/auth/login` (panel web). 401 si falta o es inválido. En escrituras autenticadas por cookie se exige además el header `X-CSRF-Token` (ver Seguridad).
- **🔒 kiosko o admin** — lo anterior **o** los headers `X-PC-Id` + `X-Kiosk-Key` de una PC (`require_kiosk_or_admin`). Un kiosko solo puede escribir datos de su propia PC (403 si no) y tiene límite de lecturas/escrituras por minuto.

### Autenticación del panel
| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `POST` | `/auth/login` | pública | `{username, password}` → `{access_token, token_type}` + cookies `access_token`/`csrf_token`. 401 si no coincide; 429 tras `LOGIN_MAX_INTENTOS` fallos desde la misma IP. |
| `POST` | `/auth/logout` | pública | Revoca el JWT recibido (cookie o Bearer) hasta su expiración y borra las cookies. |
| `GET` | `/auth/me` | 🔒 admin | `{username}` — el panel lo usa para saber si la sesión sigue viva. |
| `PUT` | `/auth/password` | 🔒 admin | `{password_actual, password_nueva}` → token nuevo. La nueva debe tener 12–128 caracteres, ser distinta del usuario y no estar publicada en el repo (422 si no). 401 si `password_actual` no coincide. |

### Kiosko → servidor
| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `POST` | `/sync` | 🔒 kiosko o admin | `{pc_id, pc_nombre?, ip?, sesiones: [Sesion]}` (máx. `SYNC_MAX_SESIONES`) → `{recibidos, insertados, estudiantes_creados, timestamp}`. Upsert idempotente, ver Lógica de negocio. 422 si alguna sesión es de otra PC. |
| `POST` | `/estado` | 🔒 kiosko o admin | Heartbeat (~cada 30 s) `{pc_id, pc_nombre?, sesion_activa, carnet?, nombre?, hora_inicio?, carrera?, facultad?, sexo?, fecha_nacimiento?}` → `{ok, timestamp}`. Actualiza el estado en vivo y `pcs.ultima_conexion`. |
| `POST` | `/pcs/{pc_id}/hardware` | 🔒 kiosko o admin | Telemetría del agente de hardware → `{ok, ultimo_mantenimiento, estado_mantenimiento}`. |
| `POST` | `/estudiantes` | 🔒 kiosko o admin | Alta (201) → `{carnet}`. 409 si el carnet ya existe, 422 si carrera/facultad no es una combinación del catálogo. |
| `GET` | `/estudiantes/{carnet}` | 🔒 kiosko o admin | 404 si no existe. Un kiosko tiene límite de `ESTUDIANTES_MAX_LECTURAS_MIN` consultas por minuto. |
| `PUT` | `/estudiantes/{carnet}` | 🔒 kiosko o admin | Actualiza la ficha (404 si no existe, 422 fuera de catálogo). Un kiosko solo puede editar al estudiante con sesión activa en su PC según su último `POST /estado` (403 si no). |

### Panel de administración
| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `GET` | `/estado` | 🔒 admin | Estado en vivo de todas las PCs, con `estado_pc` = `en_uso` / `disponible` / `no_disponible` (sin heartbeat en 2 min). |
| `GET` | `/estudiantes` | 🔒 admin | Lista completa, ordenada por nombre (NULLs al final). |
| `GET` | `/estudiantes/catalogo` | 🔒 admin | Facultades y sus carreras válidas (`models/catalogo.py`). |
| `DELETE` | `/estudiantes/{carnet}` | 🔒 admin | 204. 404 si no existe, 409 si tiene sesiones registradas. |
| `GET` | `/pcs` | 🔒 admin | Lista de mantenimiento: specs, salud, minutos de uso desde el último mantenimiento, `estado_mantenimiento` y `tiene_api_key`. |
| `POST` | `/pcs/{pc_id}/mantenimiento` | 🔒 admin | Marca `ultimo_mantenimiento = now()` y reinicia las horas acumuladas. 404 si la PC no existe. |
| `POST` | `/pcs/{pc_id}/api-key` | 🔒 admin | Genera o rota la API key de la PC; el valor en texto plano se devuelve una única vez. |
| `DELETE` | `/pcs/{pc_id}/api-key` | 🔒 admin | Revoca la key de esa PC (204). 404 si la PC no existe. |
| `GET` | `/reportes/sesiones` | 🔒 admin | `?fecha&pc_id&carnet&carrera&limit(≤5000)&offset` → sesiones del día (default: hoy), históricas + en curso aún no sincronizadas. |
| `GET` | `/reportes/pcs-activas` | 🔒 admin | PCs con `ultima_conexion` en los últimos 5 minutos. |
| `GET` | `/reportes/resumen-dia` | 🔒 admin | `?fecha` → total de sesiones, estudiantes únicos, PCs usadas, minutos promedio. |
| `GET` | `/reportes/estadisticas` | 🔒 admin | `?desde&hasta` (default: últimos 30 días) → totales y agregados por día, hora, carrera, facultad, sexo y PC. |

(`routers/pcs.py` y `routers/hardware.py` comparten el prefijo `/pcs` con tags distintos; las subrutas no colisionan.)

### Otros
| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `GET` | `/health` | pública | `{"status": "ok"}`. Solo comprueba que el proceso responde (el kiosko la usa para detectar si hay red). |
| `GET` | `/health/ready` | pública | `{"status": "ok", "db": "ok"}`, o 503 si MySQL no responde en 2 s. La usa el `HEALTHCHECK` del contenedor. |
| `GET` | `/metrics` | pública | Solo con `ENABLE_METRICS=true`. Métricas Prometheus de requests (sin PII). |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | pública | Solo con `ENABLE_API_DOCS=true`. |
| `GET` | `/`, `/panel/*` | pública | Panel web estático. |

## Lógica de negocio no obvia

**Doble fuente de verdad para sesiones.** `estado_pcs` es un snapshot en vivo (se sobrescribe en cada heartbeat), mientras que `sesiones` es el histórico autoritativo, poblado de forma asíncrona vía `/sync`. Una sesión puede estar activa en `estado_pcs` sin haberse sincronizado aún a `sesiones`. Por eso los reportes (`db/reportes.py`, `db/pcs.py::listar_mantenimiento`) hacen `UNION ALL` de ambas fuentes con un `NOT EXISTS` para no contar dos veces una sesión que ya llegó a `sesiones` (abierta o cerrada). Las estadísticas por rango (`/reportes/estadisticas`) usan solo `sesiones`.

**Sincronización idempotente (`db/sesiones.py::registrar_sync`).** Cada sesión del payload se inserta con `INSERT ... ON DUPLICATE KEY UPDATE`, donde `hora_fin`/`sincronizado`/`timestamp_sync` solo se sobrescriben si el nuevo `hora_fin` no es `NULL`. Esto permite reenviar la misma sesión (por su `id`, generado por el cliente) sin duplicarla ni perder estado, y cerrarla cuando llega con `hora_fin`; si el `id` ya pertenece a otra PC, la fila no se toca. El cliente actual solo envía sesiones ya cerradas. Los fallos de upsert de estudiante se registran individualmente sin abortar el resto del lote.

**`/sync` y `/estado` no editan estudiantes.** `db/estudiantes.py::asegurar_desde_sesion` (usado en `db/sesiones.py` y `db/estado.py`) solo crea la ficha si el carnet no existe, para cumplir la FK de `sesiones`; nunca modifica una existente. Editar datos es exclusivo de `PUT /estudiantes/{carnet}`, que tiene rate limit por request. En `/sync`, cada estudiante creado cuenta como una escritura más en `KIOSKO_MAX_ESCRITURAS_MIN`.

**Umbrales de mantenimiento (`db/umbrales.py`).**
- `< 300 h` → `"optimo"`
- `300–400 h` → `"pendiente"` (`UMBRAL_PENDIENTE_HORAS = 300`)
- `> 400 h` → `"critico"` (`UMBRAL_CRITICO_HORAS = 400`)

Estas horas son `horas_uso_acumuladas` reportadas por el agente de hardware del cliente (tiempo real de encendido), **distintas** de `minutos_uso_desde_mantenimiento` (suma de duraciones de sesiones desde el último mantenimiento) — el panel muestra ambas métricas juntas en la vista de PCs.

## ⚠️ Seguridad — leer antes de desplegar en producción

- **Todo endpoint que lee o escribe datos exige credencial.** `routers/auth.py` expone `require_auth` (JWT de admin), aplicada a nivel de router en `pcs.py` y `reportes.py`, a `GET /estado` y a `GET /estudiantes`, `GET /estudiantes/catalogo` y `DELETE /estudiantes/{carnet}`; y `require_kiosk_or_admin` (JWT de admin **o** API key de la PC), para lo que consume el kiosko, que no maneja JWT: `POST /sync`, `POST /estado`, `POST /pcs/{id}/hardware` y `POST`/`GET`/`PUT /estudiantes`. Solo son públicos `/auth/login`, `/auth/logout`, `/health`, `/health/ready`, el panel estático y, si se activan, `/metrics` y `/docs`. Ver la tabla de Endpoints.
- **El panel guarda el JWT en una cookie `HttpOnly`, no en `sessionStorage`.** `POST /auth/login` y `PUT /auth/password` setean dos cookies (`_set_auth_cookies` en `routers/auth.py`): `access_token` (`HttpOnly`, `SameSite=Strict`, `Secure` si el panel se sirve por HTTPS, sea por TLS propio o con `BEHIND_HTTPS_PROXY` — mismo criterio que el HSTS de `SecurityHeadersMiddleware`) e ilegible por tanto desde JS, y `csrf_token` (legible, sin datos sensibles) para el patrón doble-submit: en escrituras (`POST`/`PUT`/`PATCH`/`DELETE`) autenticadas por la cookie, el servidor exige que el header `X-CSRF-Token` coincida con el claim `csrf` firmado dentro del propio JWT (`_verificar_csrf`) — defensa en profundidad además del `SameSite=Strict`, que ya bloquea el envío de la cookie en requests de origen cruzado en navegadores actuales. `GET /auth/me` (protegido por `require_auth`) es lo que el panel llama al cargar la página para saber si la sesión sigue viva, ya que no puede leer la cookie; `POST /auth/logout` revoca en el servidor el JWT con el que se llama (cookie o `Authorization: Bearer`: su `jti` queda en la tabla `tokens_revocados` hasta su `exp`, y `verify_token` lo rechaza desde ese momento aunque alguien conserve una copia) y limpia ambas cookies. La autenticación por `Authorization: Bearer` (para scripts/API que no son un navegador y por tanto no arriesgan CSRF) se mantiene intacta y no exige `X-CSRF-Token`.
- **Los JWT de admin se revocan al cambiar la contraseña, no solo al expirar.** Por defecto duran `TOKEN_EXPIRE_HOURS` horas (24 si no se define en el `.env`), pero `verify_token` además rechaza cualquier token cuyo `iat` (momento de emisión) sea anterior al último `PUT /auth/password` de ese usuario (columna `admins.actualizado`), aunque el token todavía no haya expirado — así un token filtrado (XSS, malware, red sin TLS) deja de servir apenas el admin nota el compromiso y cambia su contraseña, sin tener que esperar a que venza solo. `PUT /auth/password` devuelve un token nuevo en la misma respuesta para que la sesión que lo pidió no se corte a sí misma; cualquier otra sesión con el token viejo sí queda cerrada en su siguiente petición. La comparación se hace toda en UTC calculado en Python (`datetime.now(UTC)`, tanto para `iat` como para `admins.actualizado` — ver `db/admins.py`), a propósito para no depender de la zona horaria del contenedor de MySQL (`America/El_Salvador` en este despliegue, ver más abajo).
- **Auth de servicio para el kiosko en `/estudiantes` (H-011, resuelto).** `POST /estudiantes`, `GET /estudiantes/{carnet}` y `PUT /estudiantes/{carnet}` usan `require_kiosk_or_admin`: aceptan el JWT de admin **o** el header `X-Kiosk-Key` de una PC. `GET /estudiantes` y `DELETE /estudiantes/{carnet}` siguen siendo solo-admin.
- **API key por PC, no una sola compartida.** Cada PC autentica con su propia key: el kiosko manda `X-Kiosk-Key` junto con `X-PC-Id`, y el servidor la valida contra el hash guardado en `pcs.api_key_hash` para ese `pc_id` (`hash_api_key`/`generar_api_key` en `routers/auth.py`). El admin genera o rota la key de una PC desde el panel (pestaña "PCs", botón "Generar/Rotar API key" → `POST /pcs/{pc_id}/api-key`) y puede revocar solo esa PC (`DELETE /pcs/{pc_id}/api-key`) sin tocar las demás; el valor en texto plano se muestra una única vez y el servidor solo guarda su hash. Los logs de escritura/lectura de estudiantes, `/sync`, `/estado` y `/pcs/{id}/hardware` ya registran el `actor.sub`, que con este esquema es el `pc_id` real en vez de la etiqueta genérica `"kiosko"`. Mientras una PC no tenga key propia configurada, `require_kiosk_or_admin` acepta como respaldo la `KIOSK_API_KEY` compartida del `.env` (logueando una advertencia) — pensado solo como puente durante la migración de las PCs existentes, no como modo normal de operación. Ese respaldo exige igualmente `X-PC-Id` y queda atado a esa PC (solo puede escribir sus propios datos), y deja de valer para una PC en cuanto se le genera una key propia: a partir de ahí la clave compartida da 401 para esa PC.
- **CORS cerrado por defecto.** `main.py` arma `allow_origins` desde la variable de entorno `CORS_ORIGINS` (vacía por defecto → sin orígenes cross-origin permitidos; el panel se sirve desde el mismo origen que la API) y usa `allow_credentials=False`. Si necesitás servir el panel desde otro origen, agregalo explícitamente en `CORS_ORIGINS` (separado por comas) — no actives `allow_credentials` junto con un origen comodín.
- **`SECRET_KEY` es obligatoria, sin fallback.** `routers/auth.py` la exige con `_require_env("SECRET_KEY")`: si está vacía o ausente, el servidor **no arranca** (lanza `RuntimeError` en vez de firmar JWT con un secreto conocido o vacío). `.env.example` la deja vacía a propósito para forzar que la definas con un valor fuerte (`openssl rand -hex 32`) antes de desplegar.
- **Credenciales de admin: viven en la base de datos, no en el `.env`.** Hay una tabla `admins` (`username`, `password_hash`) — `POST /auth/login` compara contra ella, no contra variables de entorno. `ADMIN_USER`/`ADMIN_PASS_HASH` en el `.env` solo se usan **una vez**, para sembrar el primer administrador si la tabla está vacía (`db/schema.py::_sembrar_admin_inicial`); después de eso quedan obsoletas — cambiarlas en el `.env` y reiniciar el servidor **no** cambia la contraseña real. Así quien hace el despliegue puede fijar unas credenciales iniciales conocidas, y el administrador real las cambia desde el panel (botón "Cambiar contraseña", `PUT /auth/password`) sin que quien desplegó llegue a conocer la contraseña definitiva.
  - `ADMIN_PASS_HASH` **no es la contraseña en texto plano**, es un hash PBKDF2-HMAC-SHA256 (`pbkdf2_sha256$<iteraciones>$<salt>$<hash>`, 600 000 iteraciones — recomendación OWASP 2023+). Generalo con `python3 servidor/generar_hash_admin.py` (útil sobre todo si querés fijar una contraseña inicial custom sin exponerla a quien despliega; mismo principio que el PIN de administrador del kiosko, ver `biblioteca_cliente/cliente/setup.py`). **No es opcional:** el valor de ejemplo del `.env.example` es un hash real y público (contraseña "cambiar-esta-contrasena"), y `db/schema.py::_sembrar_admin_inicial` lo reconoce y se niega a crear el admin inicial con él — dejarlo tal cual deja el panel sin ningún administrador.
  - Si la tabla `admins` queda vacía y `ADMIN_USER`/`ADMIN_PASS_HASH` no están configuradas, tienen formato inválido, o `ADMIN_PASS_HASH` es el hash de ejemplo público de arriba, el servidor arranca igual pero loguea una advertencia/error: nadie podrá iniciar sesión hasta sembrar un admin (por `.env` con un hash propio + reinicio, o insertándolo manualmente en la tabla).

## Despliegue

La guía completa (variables de entorno, TLS, backups, checklist de seguridad y orden de despliegue del servidor y las 16 PCs) está en [`docs/desarrollo/despliegue.md`](docs/desarrollo/despliegue.md). Resumen:

```bash
cp .env.example .env
# Obligatorias: DB_NAME, DB_USER, DB_PASSWORD, MYSQL_ROOT_PASSWORD, SECRET_KEY
# (openssl rand -hex 32), ADMIN_USER, ADMIN_PASS_HASH propio
# (python3 servidor/generar_hash_admin.py — el del ejemplo se rechaza) y,
# en producción, SERVER_BIND_IP (IP de la PC maestra en la LAN de los kioscos).

# producción (no monta código, sin --reload, MySQL sin publicar)
docker compose -f docker-compose.prod.yml up -d --build

# desarrollo (código montado + --reload; API en 127.0.0.1:8000, MySQL en 127.0.0.1:3307)
docker compose up -d --build

# datos de demostración para el panel (solo en desarrollo)
docker compose exec -T servidor python seed_demo.py --reset
```

El panel queda en `http://<host>:8000/` (o `/panel`).

## Panel web de administración

SPA sin build step servida como estáticos bajo `/panel` (y también en `/`). Login con usuario/contraseña de admin (JWT en una cookie `HttpOnly` + CSRF de doble-submit — ver sección de Seguridad).

- **Sesiones** (`views/sesiones.html` + `sesiones.js`): tabla de sesiones del día con filtros (fecha, carrera, facultad, PC, carnet/nombre), resumen del día con el número de PCs activas (conectadas en los últimos 5 min), exportación a CSV de la tabla filtrada, ticker que actualiza cada minuto la duración de sesiones en curso, auto-refresh cada 30s. Las sesiones de "invitado" (sin carnet) se marcan con badge amarillo.
- **PCs** (`views/pcs.html` + `pcs.js`): grid de tarjetas con estado en vivo (en uso / disponible / sin conexión) + tabla de mantenimiento con specs resumidas, badges óptimo/pendiente/crítico, botón para registrar mantenimiento y generación/rotación/revocación de la API key de cada PC (también para una PC nueva por su `PC_ID`).
- **Estudiantes** (`views/estudiantes.html` + `estudiantes.js`): tabla con búsqueda local, modal de alta/edición (facultad y carrera sugeridas desde `/estudiantes/catalogo`) y botón de eliminar (el servidor lo rechaza si el estudiante tiene sesiones).
- **Estadísticas** (`views/estadisticas.html` + `estadisticas.js`): carga Chart.js dinámicamente desde CDN; rangos rápidos (7/30/90/365 días) o manuales; gráficos de sesiones por día, distribución por hora, doughnut por sexo, y barras horizontales de top carreras / facultad / uso por PC.

`app.js` orquesta el ruteo entre tabs (fetch de fragmentos HTML) y el auto-refresh; `api.js` centraliza las llamadas HTTP (cookie de sesión + header `X-CSRF-Token`) y el manejo de 401; `cuenta.js` el cambio de contraseña. Las fechas y horas se muestran en la hora local del navegador; el servidor guarda hora local de El Salvador.

La paleta de colores del panel (`style.css`) replica la identidad visual institucional de la UES: rojo escarlata `#8B0E13`, negro `#1A171B`.

## Otros detalles a tener en cuenta

- `servidor/routers/__init__.py` está vacío; los routers se importan explícitamente por submódulo en `main.py`.
- `db/connection.py::ConnectionWrapper` envuelve PyMySQL con una API estilo `sqlite3` (`.execute()`, `.executescript()`, etc.) para que el resto del código luzca uniforme aunque el motor real sea MySQL. `executescript()` divide el SQL ingenuamente por `;`, suficiente para el DDL actual pero no soportaría sentencias con `;` embebido.
- El campo `sesiones.id` es generado y enviado por el cliente kiosko (no autoincremental), consistente con el patrón offline-first.
- `init_db()` corre en cada arranque (`lifespan` de FastAPI en `main.py`): crea las tablas que falten y aplica las migraciones pendientes.
- Horas: `TZ=America/El_Salvador` en ambos contenedores; las columnas `DATETIME` guardan hora local sin zona, salvo `admins.actualizado`, `tokens_revocados.expira` y `schema_migraciones.aplicada`, que van en UTC.
- El `.gitignore` revela piezas del ecosistema más amplio no incluidas en este repo: `cloudflared/` (túnel Cloudflare para exponer el servidor sin abrir puertos) y artefactos del cliente de escritorio PyQt6 (`.pc_id`, `config.ini`, empaquetado para Windows).
