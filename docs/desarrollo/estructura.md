# Estructura del proyecto — Biblioteca Servidor

Documentación de desarrollo, parte 2 de 2. Para cómo desplegar, ver [`despliegue.md`](./despliegue.md). Para la guía de uso del panel, ver [`../usuario.md`](../usuario.md).

## Qué problema resuelve

- Saber **qué estudiante usa qué PC y durante cuánto tiempo**, incluyendo un modo "invitado" para personal no estudiantil (administrativo, docente, visitante) sin carnet.
- Permitir que los kioscos de cada PC funcionen **sin conexión continua**: acumulan sesiones localmente y las sincronizan por lotes cuando hay red (`/sync`).
- Mostrar en **tiempo real** qué PCs están libres o en uso (`/estado`).
- Recibir **telemetría de hardware** de cada PC (specs, temperatura, salud de disco, horas de encendido) para anticipar mantenimiento preventivo.
- Generar **reportes y estadísticas** de uso (día, hora, carrera, facultad, sexo, PC).
- Servir un **panel web** de administración para todo lo anterior.

## Arquitectura y stack

- **FastAPI** + **Pydantic** sobre **Uvicorn** (ASGI).
- **MySQL 8.4** accedido con **SQL crudo** vía `PyMySQL` (sin ORM).
- **JWT** (`PyJWT`) para el login del panel administrativo.
- **Docker Compose** para orquestar servidor + base de datos.
- **Panel web**: HTML/CSS/JS vanilla sin build step, con **Chart.js** desde CDN solo en la vista de estadísticas.

Dependencias (`servidor/requirements.txt`): `fastapi`, `uvicorn[standard]`, `pydantic`, `PyJWT`, `PyMySQL`, `prometheus-client`. Requiere Python 3.11+ (la imagen Docker usa 3.12).

## Estructura de carpetas

```
servidor/
├── main.py               # entry point: registra routers, CORS, monta el panel, /health
├── db/                    # acceso a datos (SQL crudo vía PyMySQL)
│   ├── connection.py       # ConnectionWrapper: envuelve PyMySQL con API estilo sqlite3
│   ├── schema.py            # DDL de todas las tablas + migraciones versionadas
│   ├── ESQUEMA.md            # diagrama ER y detalle de cada tabla (fuente de verdad: schema.py)
│   ├── estudiantes.py, pcs.py, sesiones.py, estado.py, hardware.py, reportes.py, umbrales.py, admins.py
├── models/                # esquemas Pydantic de entrada/salida (catalogo.py: facultades y carreras válidas)
├── routers/               # endpoints FastAPI, uno por dominio
├── panel/                 # SPA estática (HTML/CSS/JS) servida en /panel y /
├── scripts/               # backup/restore de MySQL, CA interna y certificados TLS
├── tests/                 # pytest (sin MySQL real: la capa db se reemplaza por dobles)
├── Dockerfile, docker-entrypoint.sh, healthcheck.py
└── requirements.txt
```

`servidor/routers/__init__.py` está vacío; los routers se importan explícitamente por submódulo en `main.py`.

## Modelo de datos

Diagrama ER completo y detalle campo por campo en [`servidor/db/ESQUEMA.md`](../../servidor/db/ESQUEMA.md) (dentro del código, fuente de verdad: `schema.py::init_db()`). Resumen de tablas, todas `ENGINE=InnoDB`:

| Tabla | Campos principales | Notas |
|---|---|---|
| `estudiantes` | `carnet` (PK), `nombre`, `fecha_nacimiento` (solo año, tipo `YEAR`), `carrera`, `facultad`, `sexo`, `fecha_registro` | El kiosko solo captura el año de nacimiento |
| `pcs` | `pc_id` (PK), `nombre`, `ultima_conexion`, `ip_reportada`, `ultimo_mantenimiento`, `api_key_hash`, `api_key_generada` | Identidad estable de cada PC física y hash de su API key. `ultima_conexion` se actualiza en cada `/estado` y `/sync` |
| `sesiones` | `id` (PK, **generado por el cliente**), `pc_id` (FK), `carnet` (FK, nullable → modo invitado), `hora_inicio`, `hora_fin` (NULL = en curso), `fecha`, `sincronizado`, `timestamp_sync` | Histórico autoritativo de uso |
| `estado_pcs` | `pc_id` (PK/FK), `pc_nombre`, `sesion_activa`, `carnet` (FK, `ON DELETE SET NULL`), `nombre`, `hora_inicio`, `ultima_actualizacion` | Snapshot en vivo, 1 fila por PC |
| `pcs_hardware` | `pc_id` (PK/FK), `hostname`, `mac_address`, `cpu`, `ram_total_mb`, `almacenamiento_total_gb`, `sistema_operativo`, `temperatura_cpu_c`, `disco_smart_ok`, `horas_uso_acumuladas`, `ultima_lectura` | Telemetría del agente de hardware del cliente |
| `admins` | `username` (PK), `password_hash`, `actualizado` | Administradores del panel |
| `tokens_revocados` | `jti` (PK), `expira` | JWT dados de baja por `POST /auth/logout` hasta que expiran |
| `schema_migraciones` | `version` (PK), `descripcion`, `aplicada` | Migraciones de esquema ya aplicadas |

`sesiones` no tiene `ON DELETE` en su FK a `estudiantes` — borrar un estudiante con sesiones asociadas falla con conflicto (`DELETE /estudiantes/{carnet}` → 409).

No se usa Alembic: una base nueva nace completa desde los `CREATE TABLE IF NOT EXISTS` de `init_db()`, y las anteriores se ponen al día con las migraciones versionadas de `MIGRACIONES` (`db/schema.py`), que se aplican una sola vez y quedan registradas en `schema_migraciones`. Reglas para agregar una: ver el comentario en `schema.py` y [`ESQUEMA.md`](../../servidor/db/ESQUEMA.md).

## Endpoints de la API

> 🔒 = requiere JWT de admin válido, por `Authorization: Bearer <token>` (scripts/API) o por la cookie `access_token` que setea `/auth/login` (panel web) — 401 si falta o es inválido. Los marcados **kiosko o admin** aceptan también los headers `X-Kiosk-Key` + `X-PC-Id` de una PC (`require_kiosk_or_admin`, ver más abajo) — el cliente de escritorio no maneja JWT, así que usa esta vía. En escrituras (🔒 sin ser kiosko) autenticadas por la cookie, además se exige un header `X-CSRF-Token` (ver "Panel web" más abajo); autenticando por `Authorization: Bearer` no hace falta.

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `POST` | `/auth/login` | pública | `{username, password}` → `{access_token, token_type}` + cookies `access_token`/`csrf_token` |
| `POST` | `/auth/logout` | pública | Revoca el JWT recibido (cookie o Bearer) hasta su expiración y limpia las cookies `access_token`/`csrf_token` |
| `GET` | `/auth/me` | 🔒 | `{"username": ...}` — usado por el panel para saber si la sesión (cookie) sigue viva |
| `PUT` | `/auth/password` | 🔒 | Cambiar contraseña propia del admin autenticado |
| `POST` | `/sync` | 🔒 kiosko o admin | Recibe lote de sesiones offline-first (upsert idempotente) |
| `POST` | `/estado` | 🔒 kiosko o admin | Heartbeat (~30 s) de estado en vivo de una PC; también actualiza `pcs.ultima_conexion` |
| `GET` | `/estado` | 🔒 | Estado en vivo de todas las PCs con `estado_pc` = `en_uso` / `disponible` / `no_disponible` (sin heartbeat en 2 min) |
| `POST` | `/estudiantes` | 🔒 kiosko o admin | Registra estudiante (201, 409 si ya existe) |
| `GET` | `/estudiantes` | 🔒 solo admin | Lista completa |
| `GET` | `/estudiantes/catalogo` | 🔒 solo admin | Facultades y sus carreras válidas (`models/catalogo.py`). `POST`/`PUT /estudiantes` rechazan con 422 una combinación carrera/facultad fuera de este catálogo; `/sync` y `/estado` no rechazan el payload, pero la descartan (guardan `NULL`). |
| `GET` | `/estudiantes/{carnet}` | 🔒 kiosko o admin | 404 si no existe |
| `PUT` | `/estudiantes/{carnet}` | 🔒 kiosko o admin | Actualiza campos. Un kiosko solo edita al estudiante con sesión activa en su PC (403 si no) |
| `DELETE` | `/estudiantes/{carnet}` | 🔒 solo admin | 204, 409 si tiene sesiones (FK) |
| `GET` | `/pcs` | 🔒 | Lista de mantenimiento consolidada (incluye `tiene_api_key` por PC) |
| `POST` | `/pcs/{pc_id}/mantenimiento` | 🔒 | Marca `ultimo_mantenimiento = now()` y reinicia `horas_uso_acumuladas` a 0 (404 si la PC no existe) |
| `POST` | `/pcs/{pc_id}/api-key` | 🔒 solo admin | Genera/rota la API key de una PC, devuelve el valor en texto plano una única vez |
| `DELETE` | `/pcs/{pc_id}/api-key` | 🔒 solo admin | Revoca la API key de una PC (204) |
| `POST` | `/pcs/{pc_id}/hardware` | 🔒 kiosko o admin | Heartbeat de telemetría de hardware |
| `GET` | `/reportes/sesiones` | 🔒 | Sesiones del día (default: hoy), históricas + en curso. Filtros: `fecha`, `pc_id`, `carnet`, `carrera`, `limit` (≤5000), `offset` |
| `GET` | `/reportes/pcs-activas` | 🔒 | PCs con `ultima_conexion` en últimos 5 min |
| `GET` | `/reportes/resumen-dia` | 🔒 | Totales del día |
| `GET` | `/reportes/estadisticas` | 🔒 | Agregados por día/hora/carrera/facultad/sexo/PC, `desde`/`hasta` (default: últimos 30 días) |
| `GET` | `/health` | pública | `{"status": "ok"}` (liveness, no toca MySQL) |
| `GET` | `/health/ready` | pública | `SELECT 1` contra MySQL; 503 si no responde. Usada por el `HEALTHCHECK` |
| `GET` | `/metrics` | pública | Solo con `ENABLE_METRICS=true`. Métricas Prometheus de requests (sin PII) |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | pública | Solo con `ENABLE_API_DOCS=true` |
| `GET` | `/`, `/panel/*` | pública | Sirve el panel web estático |

Nota: `routers/pcs.py` y `routers/hardware.py` comparten el prefijo `/pcs` con tags distintos (intencional, las subrutas no colisionan); ambos exigen auth (`pcs.py` vía `require_auth`, `hardware.py` vía `require_kiosk_or_admin`).

## Lógica de negocio no obvia

**Doble fuente de verdad para sesiones.** `estado_pcs` es un snapshot en vivo (se sobrescribe en cada heartbeat); `sesiones` es el histórico autoritativo, poblado async vía `/sync`. Una sesión puede estar activa en `estado_pcs` sin haberse sincronizado aún. Los reportes (`db/reportes.py`, `db/pcs.py::listar_mantenimiento`) hacen `UNION ALL` de ambas fuentes con `NOT EXISTS` para no contar dos veces una sesión que ya llegó a `sesiones` (abierta o cerrada). `/reportes/estadisticas` usa solo `sesiones`.

**Sincronización idempotente (`db/sesiones.py::registrar_sync`).** Cada sesión se inserta con `INSERT ... ON DUPLICATE KEY UPDATE`, donde `hora_fin`/`sincronizado`/`timestamp_sync` solo se sobrescriben si el nuevo `hora_fin` no es `NULL`. Permite reenviar la misma sesión (por su `id`, generado por el cliente) sin duplicarla, y cerrarla cuando llega con `hora_fin`; si el `id` ya pertenece a otra PC, la fila no se toca. El cliente actual solo envía sesiones ya cerradas. Fallos de upsert de estudiante se registran individualmente sin abortar el resto del lote.

**`/sync` y `/estado` no editan estudiantes.** `db/estudiantes.py::asegurar_desde_sesion` (usado en `db/sesiones.py` y `db/estado.py`) solo crea la ficha si el carnet no existe, para cumplir la FK de `sesiones`; nunca modifica una existente. Editar datos es exclusivo de `PUT /estudiantes/{carnet}`, que tiene rate limit por request. En `/sync`, cada estudiante creado cuenta como una escritura más en `KIOSKO_MAX_ESCRITURAS_MIN`.

**Umbrales de mantenimiento (`db/umbrales.py`):**
- `< 300 h` → `"optimo"`
- `300–400 h` → `"pendiente"` (`UMBRAL_PENDIENTE_HORAS = 300`)
- `> 400 h` → `"critico"` (`UMBRAL_CRITICO_HORAS = 400`)

Estas horas son `horas_uso_acumuladas` (tiempo real de encendido, reportado por el agente de hardware del cliente), **distintas** de `minutos_uso_desde_mantenimiento` (suma de duraciones de sesiones desde el último mantenimiento) — el panel muestra ambas métricas juntas en la vista de PCs.

## Seguridad — resumen para desarrollo

Ver checklist operativo en [`despliegue.md`](./despliegue.md#checklist-de-seguridad-antes-de-producción). Puntos relevantes para quien toca código:

- `require_auth` (JWT, `routers/auth.py`) aplicado a nivel de router en `pcs.py`, `reportes.py`; solo a `GET` en `estado.py`; a `GET /estudiantes`, `GET /estudiantes/catalogo` y `DELETE /estudiantes/{carnet}`. Acepta el JWT por `Authorization: Bearer` o por la cookie `access_token`; vía cookie, en métodos que cambian estado exige además `X-CSRF-Token` == claim `csrf` del JWT (`_verificar_csrf`, patrón doble-submit).
- `require_kiosk_or_admin` (`routers/auth.py`) acepta JWT de admin **o** `X-Kiosk-Key` + `X-PC-Id` validados contra el hash guardado en `pcs.api_key_hash` para ese `pc_id` (`hash_api_key`); solo si esa PC no tiene key propia cae como respaldo a la `KIOSK_API_KEY` compartida del `.env` (logueando advertencia), y el actor resultante conserva el `pc_id` para que `verificar_pc_id` siga aplicando; una PC con key propia rechaza la clave compartida con 401. Usado en `POST/GET/PUT /estudiantes`, `POST /sync`, `POST /estado` y `POST /pcs/{pc_id}/hardware`. La key de cada PC se genera/rota/revoca solo-admin en `routers/pcs.py` (`POST`/`DELETE /pcs/{pc_id}/api-key`).
- `TRUSTED_PROXIES` (`routers/auth.py`) acota en qué IPs se confía el header `X-Forwarded-For` para el rate limiting de `/auth/login` (se toma la IP más a la derecha que no sea un proxy de confianza, nunca la primera, que la controla el cliente); vacío por defecto (siempre usa la IP de la conexión TCP directa). Las entradas de `_intentos_fallidos` se purgan solas cuando expiran y no vuelven a fallar.
- Credenciales de admin viven en la tabla `admins` (no en `.env`); `ADMIN_USER`/`ADMIN_PASS_HASH` solo siembran el primer admin si la tabla está vacía (`db/schema.py::_sembrar_admin_inicial`).
- `db/connection.py::ConnectionWrapper` envuelve PyMySQL con API estilo `sqlite3` (`.execute()`, `.executescript()`) para que el resto del código luzca uniforme. `executescript()` divide el SQL ingenuamente por `;` — suficiente para el DDL actual, no soportaría sentencias con `;` embebido.
- `sesiones.id` es generado y enviado por el cliente kiosko (no autoincremental), consistente con el patrón offline-first.
- `init_db()` corre en cada arranque (`lifespan` en `main.py`): crea las tablas que falten y aplica las migraciones pendientes.
- `limitar_lecturas_estudiante` / `limitar_escrituras_kiosko` limitan por credencial (el `pc_id` del kiosko), no por IP; el panel (JWT) está exento. Los contadores viven en memoria de un solo proceso: no correr más de un worker (`docker-entrypoint.sh` aborta si `UVICORN_WORKERS` ≠ 1).

## Panel web de administración (para quien lo modifica)

SPA sin build step servida como estáticos bajo `/panel` (y también en `/`). Login con usuario/contraseña de admin; la sesión ya no se guarda en `sessionStorage`, vive en la cookie `access_token` (`HttpOnly`, así un XSS futuro no podría leerla) que setea `/auth/login`. Al cargar la página, `App.init()` llama a `GET /auth/me` para saber si esa cookie sigue siendo válida (no puede leerla directamente). El panel sí lee la cookie complementaria `csrf_token` (no `HttpOnly`) para reenviarla como header `X-CSRF-Token` en cada escritura (`API.fetchRaw`, `js/api.js`) — es el lado "doble submit" que el servidor valida contra el claim `csrf` firmado dentro del JWT.

| Vista | Archivos | Contenido |
|---|---|---|
| Sesiones | `views/sesiones.html`, `js/sesiones.js` | Tabla del día con filtros, resumen (incluye PCs activas de `/reportes/pcs-activas`), export CSV de la tabla filtrada, ticker de duración cada minuto, auto-refresh 30s. Invitados con badge amarillo |
| PCs | `views/pcs.html`, `js/pcs.js` | Grid de estado en vivo + tabla de mantenimiento con specs, badges óptimo/pendiente/crítico, registrar mantenimiento, generar/rotar/revocar API key |
| Estudiantes | `views/estudiantes.html`, `js/estudiantes.js` | Tabla con búsqueda local, modal de alta/edición (catálogo de facultades/carreras), eliminar |
| Estadísticas | `views/estadisticas.html`, `js/estadisticas.js` | Chart.js desde CDN, rangos rápidos (7/30/90/365 días) o manuales |

`js/app.js` orquesta el ruteo entre tabs (fetch de fragmentos HTML) y el auto-refresh; `js/api.js` centraliza las llamadas HTTP con el token JWT y el manejo de 401. `js/cuenta.js` maneja el cambio de contraseña.

Paleta institucional UES en `style.css`: rojo escarlata `#8B0E13`, negro `#1A171B`.

## Otros detalles a tener en cuenta

- Horas: `TZ=America/El_Salvador` en ambos contenedores; los `DATETIME` guardan hora local sin zona (el panel las muestra tal cual, sin convertir), salvo `admins.actualizado`, `tokens_revocados.expira` y `schema_migraciones.aplicada`, que van en UTC. El panel calcula "hoy" con la fecha local del navegador (`fechaLocalISO` en `js/app.js`).
- `.gitignore` revela piezas del ecosistema más amplio no incluidas en este repo: `cloudflared/` (túnel Cloudflare) y artefactos del cliente PyQt6 (`.pc_id`, `config.ini`, empaquetado Windows).
- El contrato de API completo (servidor ↔ cliente) también está documentado en el repo índice `biblioteca` (README), que enlaza ambos repos hermanos.
