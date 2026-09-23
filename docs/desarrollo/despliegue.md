# Despliegue — Biblioteca Servidor

Documentación de desarrollo, parte 1 de 2. Para cómo está organizado el código, ver [`estructura.md`](./estructura.md). Para la guía de uso del panel, ver [`../usuario.md`](../usuario.md).

## Requisitos

- Docker + Docker Compose (recomendado), **o** Python 3.10+ y MySQL 8.4 accesible si se despliega sin Docker.
- Red local entre la PC maestra (donde corre este servidor) y las PCs hijas (kioscos de `biblioteca_cliente`).
- Opcional: túnel Cloudflare (`cloudflared/`, no incluido en este repo) para exponer el panel fuera de la red local sin abrir puertos.

## Opción recomendada: Docker Compose

Hay **dos archivos independientes**, ninguno se combina con el otro vía `-f`:

| Archivo | Uso | Diferencias clave |
|---|---|---|
| `docker-compose.yml` | Desarrollo (`docker compose up` por defecto) | Monta `./servidor` como volumen, `uvicorn --reload` (hot-reload sin rebuild), publica MySQL en `3307:3306` para conectarte con MySQL Workbench / `mysql` CLI |
| `docker-compose.prod.yml` | Producción (standalone) | No monta código (la imagen ya lo trae copiado), sin `--reload`, **no publica el puerto de MySQL** al host — `servidor` llega a `db` por la red interna de Compose |

Ambos levantan los mismos dos servicios:
- **`db`**: `mysql:8.4`, healthcheck vía `mysqladmin ping`, volumen persistente `db_data`, timezone `America/El_Salvador`.
- **`servidor`**: build desde `./servidor`, puerto `8000`, espera a que `db` esté `healthy`.

### Pasos

```bash
cp .env.example .env
```

Editar `.env` (ver tabla completa de variables más abajo). Como mínimo hay que rellenar:

- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `MYSQL_ROOT_PASSWORD`
- `SECRET_KEY` — **obligatoria**, viene vacía en el ejemplo (`openssl rand -hex 32`)
- `KIOSK_API_KEY` — opcional, solo como respaldo mientras se migran PCs a una key propia (ver más abajo); dejarla vacía cierra esa vía de respaldo

`ADMIN_PASS_HASH` trae un valor de EJEMPLO (contraseña `cambiar-esta-contrasena`, pública en este repo) que el servidor **rechaza** al sembrar el admin inicial — dejarlo tal cual deja el panel sin ningún administrador. Generar un hash propio sin exponer la contraseña a quien despliega:

```bash
python3 servidor/generar_hash_admin.py
```

Levantar los contenedores:

```bash
# desarrollo
docker compose up -d --build

# producción
docker compose -f docker-compose.prod.yml up -d --build
```

El backend queda disponible en `http://localhost:8000`, el panel en `http://localhost:8000/` o `/panel`.

### Datos de demostración (opcional)

Para poblar estudiantes, PCs, hardware, estado en vivo y sesiones históricas de ejemplo (útil para ver tablas/gráficos sin cargar datos reales):

```bash
docker compose exec -T servidor python seed_demo.py --reset
```

`--reset` repite la demo desde cero.

## Opción alternativa: local sin Docker

Requiere un MySQL accesible. Variables con default en `servidor/db/connection.py`: `DB_HOST=localhost`, `DB_PORT=3306`, usuario/contraseña `biblioteca`.

```bash
cd servidor
pip install -r requirements.txt
uvicorn main:app --reload
```

## Variables de entorno (`.env`)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `ADMIN_USER` | Sí | Usuario admin inicial. Solo se usa una vez para sembrar el primer administrador en la BD si la tabla `admins` está vacía; después el admin cambia su contraseña desde el panel y este valor deja de importar. |
| `ADMIN_PASS_HASH` | Sí | Hash PBKDF2-HMAC-SHA256 (`pbkdf2_sha256$<iter>$<salt>$<hash>`, 600 000 iteraciones) de la contraseña inicial. **No es texto plano.** Generar con `python3 servidor/generar_hash_admin.py`. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Sí | Credenciales de la base de datos MySQL. |
| `MYSQL_ROOT_PASSWORD` | Sí | Contraseña root del contenedor MySQL. |
| `DB_SSL_CA` | No | Ruta *dentro del contenedor* a un CA cert para cifrar la conexión servidor→MySQL. Sin efecto mientras `db` y `servidor` compartan la red interna de Compose (caso por defecto); solo hace falta si la base de datos se aloja fuera de esa red (managed DB en la nube, otra máquina) — puede colocarse dentro de `/certs`, reutilizando el mismo volumen que `TLS_CERTS_DIR`. |
| `SECRET_KEY` | Sí | Firma de los JWT. Viene vacía en `.env.example` — si se deja vacía (o ausente), el servidor **aborta al arrancar** con `RuntimeError` (`_require_env` en `servidor/routers/auth.py`); no existe ningún fallback ni JWT firmado con secreto vacío. Generar con `openssl rand -hex 32`. |
| `KIOSK_API_KEY` | No | Respaldo compartido del header `X-Kiosk-Key`, solo se usa cuando una PC todavía no tiene su propia key (ver "API key de cada PC" abajo); cada uso queda registrado en los logs con advertencia. Una PC que ya tiene key propia no acepta la clave compartida, y con ella cada PC solo puede escribir sus propios datos. Si queda vacía, ese respaldo queda siempre cerrado y todas las PCs deben tener su key propia generada desde el panel. |
| `CORS_ORIGINS` | No | Orígenes separados por coma para acceso cross-origin. Vacío = sin CORS extra (el panel se sirve desde el mismo origen que la API). |
| `LOGIN_MAX_INTENTOS` | No | Default 5. Intentos fallidos de `/auth/login` antes de bloquear temporalmente la IP. |
| `LOGIN_BLOQUEO_MINUTOS` | No | Default 15. Minutos de bloqueo tras exceder `LOGIN_MAX_INTENTOS`. |
| `TRUSTED_PROXIES` | No | IPs separadas por coma de reverse proxies/túneles de confianza (p. ej. Cloudflare Tunnel) autorizados a añadir a `X-Forwarded-For` la IP real del cliente para el rate limiting de `/auth/login`. Se toma la IP más a la derecha del header que no sea uno de estos proxies, porque lo que queda a su izquierda lo puede fijar el propio cliente. Vacío (default) = nunca se confía en el header, siempre se usa la IP de la conexión TCP directa. Solo hace falta si el servidor corre detrás de un proxy — si no, todas las conexiones legítimas compartirían la IP del proxy y un solo atacante podría bloquear a todos los administradores. |
| `MAX_BODY_SIZE_BYTES` | No | Default 5 000 000 (5MB). Límite de tamaño de body para `POST`/`PUT`/`PATCH`. |
| `SYNC_MAX_SESIONES` | No | Default 100. Máximo de sesiones por lote en `POST /sync`. |
| `ENABLE_API_DOCS` | No | Default deshabilitado. En `true`/`1`/`yes` habilita `/docs`, `/redoc` y `/openapi.json` (documentación interactiva de la API, sin autenticación). Dejar apagado en producción; solo activar para desarrollo local o debugging puntual. |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | No (recomendado) | Rutas *dentro del contenedor* al certificado/clave del servidor. Vacías = uvicorn sirve HTTP plano. Ver sección **TLS** abajo. |
| `TLS_CERTS_DIR` | No | Default `./certs`. Carpeta en el **host** que `docker-compose.prod.yml` monta en `/certs` (solo lectura) dentro del contenedor — ahí es donde deben estar los archivos que apuntan `TLS_CERT_PATH`/`TLS_KEY_PATH`. |
| `UVICORN_WORKERS` | No | No se usa para nada (`docker-entrypoint.sh` nunca le agrega `--workers` a uvicorn): existe solo para que, si alguien la fija en un valor distinto de `1` pensando en escalar el servicio, el contenedor aborte al arrancar en vez de correr con el rate limiting de `servidor/routers/auth.py` roto en silencio (ver más abajo). |

## TLS (cifrado entre los kioscos y este servidor)

Sin TLS, la PII de estudiantes y el header `X-Kiosk-Key` que envían los kioscos viajan **en texto plano** por la LAN del laboratorio — cualquiera en la misma red puede leerlos o alterarlos en tránsito. `biblioteca_cliente` ya rehúsa arrancar con `SERVER_URL` en `http://` hacia un host que no es `localhost`, salvo que se asuma el riesgo a propósito — ver su `docs/desarrollo/despliegue.md`.

Como el servidor normalmente solo tiene una IP de LAN (sin dominio público), no aplica una CA pública tipo Let's Encrypt. `servidor/scripts/generar_ca.sh` genera una **CA interna propia** y un certificado para la IP del servidor:

```bash
cd servidor
./scripts/generar_ca.sh 192.168.x.x      # IP real de la PC maestra en la LAN
```

Esto crea, en `<raíz del repo>/certs/` (junto a este `docker-compose.prod.yml`, gitignored — **nunca se versiona**):

| Archivo | Qué es | A dónde va |
|---|---|---|
| `ca.key` | Clave privada de la CA | Guardarla offline (USB, gestor de contraseñas). No hace falta en el servidor una vez generado `server.pem`. |
| `ca.pem` | Certificado público de la CA | Copiar a `cliente/ca.pem` en **cada uno de los 16 kioscos** — `config.ini` → `[servidor] ca_cert`. |
| `server.key` | Clave privada del servidor | Queda en la PC maestra. `TLS_KEY_PATH` en el `.env`. |
| `server.pem` | Certificado del servidor, firmado por la CA | `TLS_CERT_PATH` en el `.env`. |

En el `.env` del servidor:

```
TLS_CERT_PATH=/certs/server.pem
TLS_KEY_PATH=/certs/server.key
```

(`/certs` es la ruta *dentro del contenedor* — `docker-compose.prod.yml` monta `TLS_CERTS_DIR`, default `./certs`, ahí adentro.) Al levantar `docker compose -f docker-compose.prod.yml up -d --build` con esas variables configuradas, `servidor/docker-entrypoint.sh` le agrega automáticamente `--ssl-certfile`/`--ssl-keyfile` a `uvicorn`.

El certificado del servidor vence en ~825 días (2.25 años) — no hay renovación automática como con una CA pública, calendarizarla (volver a correr `generar_ca.sh` reusando la misma CA, o el script completo si también hace falta rotar la CA).

`servidor/scripts/verificar_vencimiento_cert.sh` avisa (código de salida != 0) cuando el certificado de servidor o la CA están a menos de 60 días de vencer, para no depender de acordarse manualmente. Agregarlo a cron en la PC maestra (semanal, por ejemplo):

```
0 8 * * 1 cd /ruta/al/repo && ./servidor/scripts/verificar_vencimiento_cert.sh >> /var/log/biblioteca-certs.log 2>&1
```

Renovar (certificado de servidor solamente, reusando la CA existente — no hace falta redistribuir nada a los kioscos):

```bash
cd servidor
./scripts/renovar_cert_servidor.sh 192.168.x.x
docker compose -f ../docker-compose.prod.yml restart servidor
```

(Si en cambio hace falta rotar también la CA, borrar `certs/ca.key`/`ca.pem` a mano y correr `generar_ca.sh` de nuevo — eso sí exige redistribuir el `ca.pem` nuevo a los 16 kioscos.)

`docker-compose.yml` (desarrollo) no necesita nada de esto: corre sobre `localhost`, que sí está permitido en `http://` sin restricción.

### Conexión servidor→MySQL

Por defecto (`DB_SSL_CA` vacía) esta conexión va sin cifrar, sin impacto práctico mientras `db` y `servidor` compartan la red interna de Docker Compose, como en ambos `docker-compose*.yml` de este repo. Si en algún momento la base de datos se mueve fuera de esa red (un managed DB en la nube, otra máquina de la LAN), fijar `DB_SSL_CA` con la ruta al CA cert correspondiente — normalmente lo entrega el propio proveedor de la base de datos; puede colocarse dentro de `/certs` para reutilizar el volumen que ya monta `TLS_CERTS_DIR`.

## Backups de MySQL

El volumen `db_data` no tiene ningún mecanismo de backup automático por sí solo (un `docker compose down -v` o un disco corrupto se lleva todo). `servidor/scripts/backup_db.sh` vuelca la base vía `mysqldump` (sin detener el contenedor) a un `.sql.gz`, y conserva los últimos 14 por defecto:

```bash
# desde la raíz del repo
./servidor/scripts/backup_db.sh /ruta/a/backups docker-compose.prod.yml
```

Para que corra solo, agregarlo a cron en la PC maestra (diario a las 3am, por ejemplo):

```
0 3 * * * cd /ruta/al/repo && ./servidor/scripts/backup_db.sh /ruta/a/backups docker-compose.prod.yml >> /var/log/biblioteca-backup.log 2>&1
```

Restaurar (DESTRUCTIVO — sobreescribe la base actual):

```bash
./servidor/scripts/restore_db.sh /ruta/a/backups/biblioteca-20260913-030000.sql.gz docker-compose.prod.yml
```

Los backups tienen la misma PII de estudiantes que la base — guardarlos fuera de la PC maestra (otro disco, almacenamiento cifrado) y nunca en el propio repo (`*.sql.gz` y `/backups/` están en `.gitignore`).

## Observabilidad

Más allá del `HEALTHCHECK` de Docker (que solo dice si el proceso responde), `GET /metrics` expone métricas en formato Prometheus (conteo y latencia de requests por endpoint/método/status — nada de negocio ni PII). Apagado por defecto; activarlo con `ENABLE_METRICS=true` en el `.env`. Sin autenticación propia — si se activa en producción, restringir el acceso a nivel de red (firewall, o que solo el scraper de Prometheus llegue a ese puerto).

## Checklist de seguridad antes de producción

- [ ] `SECRET_KEY` rellena con un valor fuerte y aleatorio (no vacía).
- [ ] Cada PC tiene su propia API key generada desde el panel (pestaña "PCs" → "Generar API key") en vez de depender de `KIOSK_API_KEY`; esta última solo debería estar rellena mientras dure la migración de PCs existentes.
- [ ] `ADMIN_PASS_HASH` propio (no el de ejemplo — el servidor lo rechaza igual, pero conviene no depender de eso).
- [ ] Desplegado con `docker-compose.prod.yml`, no con el de desarrollo (evita `--reload` y exponer el puerto de MySQL).
- [ ] `CORS_ORIGINS` configurado solo si el panel se sirve desde un origen distinto a la API (no es necesario por defecto).
- [ ] `TLS_CERT_PATH`/`TLS_KEY_PATH` configuradas (ver sección **TLS**) y `ca.pem` distribuido a los 16 kioscos — si se decide operar sin TLS a propósito, confirmar que cada `config.ini` tiene `permitir_http_inseguro = true` fijado conscientemente, no por omisión.
- [ ] Si se expone fuera de la red local, hacerlo vía túnel Cloudflare (`cloudflared/`) en lugar de abrir puertos directamente.
- [ ] `backup_db.sh` agendado en cron en la PC maestra (ver sección **Backups de MySQL**) y probado al menos una vez `restore_db.sh` contra una base de prueba.
- [ ] `ENABLE_API_DOCS` sin fijar (o en `false`) — `/docs`/`/redoc`/`/openapi.json` quedan deshabilitados.
- [ ] Una sola réplica del servicio `servidor` (los `docker-compose*.yml` de este repo no definen `deploy.replicas`, así que por defecto ya es una — solo aplica si en algún momento se orquesta distinto, p. ej. Swarm/Kubernetes). Dentro del contenedor, `docker-entrypoint.sh` ya aborta el arranque si `UVICORN_WORKERS` viene fijada en algo distinto de `1`: el rate limiting de `/auth/login` y las ventanas de lecturas/escrituras de kiosko (`servidor/routers/auth.py`) se llevan en memoria de un solo proceso, no en un almacén compartido.

## Cómo se conectan el servidor y las PCs (kioscos)

Este servidor es la mitad "PC maestra": corre en **una sola PC** de la sala (o una máquina/VM dedicada), y cada una de las PCs de la sala corre `biblioteca_cliente` como kiosko, hablándole a este servidor por la red local. No hay descubrimiento automático: cada kiosko necesita saber, de antemano, la IP (o dominio) de la PC maestra, configurada a mano una vez en `setup.py`/`config.ini` de esa PC.

- **Transporte**: HTTP(S) sobre el puerto `8000` (el que publica `docker-compose*.yml`). El cliente (`cliente/network/`) es un consumidor REST/JSON normal (`requests`), no hay WebSockets ni un protocolo propio.
- **Red**: todas las PCs deben estar en la misma LAN que la PC maestra (o alcanzarla por VPN/túnel) y el firewall de la PC maestra debe permitir entrantes al puerto `8000` desde esa LAN — no hace falta abrir nada hacia internet salvo que se use el túnel Cloudflare opcional para el panel.
- **Identidad de cada PC**: cada kiosko tiene un `PC_ID` (UUID4, generado una vez por `setup.py` en `.pc_id`) que lo identifica de forma estable ante el servidor, independiente de hostname/MAC/IP (que pueden cambiar).
- **Autenticación kiosko→servidor**: cada request del kiosko (`POST /sync`, `POST /estado`, `POST/GET/PUT /estudiantes`, `POST /pcs/{id}/hardware`) manda dos headers: `X-PC-Id` (el UUID de esa PC) y `X-Kiosk-Key` (su API key). El servidor valida la key contra el hash guardado en `pcs.api_key_hash` para ese `pc_id` exacto (`require_kiosk_or_admin` + `verificar_pc_id` en `servidor/routers/auth.py`) — una PC no puede autenticarse con el `PC_ID` de otra, ni usar la key de otra. La key se genera **desde el panel admin** (pestaña "PCs" → "Generar API key", requiere el `PC_ID` que `setup.py` mostró en esa PC) y se ve una única vez.
- **Autenticación admin→servidor**: distinta de la anterior. El panel web usa login usuario/contraseña (`POST /auth/login`) y un JWT guardado en cookie `HttpOnly`, no la API key de ninguna PC.
- **Cifrado en tránsito (TLS)**: opcional pero fuertemente recomendado — sin él, la PII de estudiantes y `X-Kiosk-Key` viajan en texto plano por la LAN. Como la PC maestra normalmente solo tiene IP interna (sin dominio público), se usa una CA interna propia generada con `servidor/scripts/generar_ca.sh` en vez de una CA pública — ver sección **TLS** arriba. El certificado de la CA (`ca.pem`) es lo único que hay que distribuir a cada kiosko.
- **Offline-first**: si la red cae, el kiosko sigue funcionando (login/registro contra su caché SQLite local, sesión con temporizador local) y acumula sesiones/cambios pendientes; los reintenta solo cuando `hay_conexion()` vuelve a dar `True`, sin intervención manual.

## Orden de despliegue del sistema completo (paso a paso)

### Fase 1 — PC maestra (este servidor)

1. Elegir qué máquina de la sala (o servidor/VM dedicado) hará de PC maestra y anotar su **IP en la LAN** (`ip a` / `ipconfig`) — todas las PCs hijas se configurarán apuntando a esa IP.
2. Instalar Docker + Docker Compose en esa máquina si no los tiene.
3. Clonar/copiar este repo (`biblioteca_servidor`) ahí y seguir la sección **Opción recomendada: Docker Compose** de arriba: `.env`, `SECRET_KEY`, `ADMIN_PASS_HASH` propio, `KIOSK_API_KEY` opcional.
4. Decidir si se usará TLS (recomendado). Si sí: correr `servidor/scripts/generar_ca.sh <IP-de-la-PC-maestra>` **ahora**, antes de configurar las PCs hijas, y completar `TLS_CERT_PATH`/`TLS_KEY_PATH` en el `.env` — ver sección **TLS** arriba.
5. Levantar con `docker compose -f docker-compose.prod.yml up -d --build`.
6. Verificar que responde: `curl http://<IP-PC-maestra>:8000/health` (o `curl -k https://<IP>:8000/health` con TLS) desde otra PC de la misma LAN — si no responde, revisar firewall de la PC maestra (puerto `8000` entrante) antes de seguir.
7. Entrar al panel (`http://<IP-PC-maestra>:8000/`), iniciar sesión con `ADMIN_USER`/la contraseña usada para generar `ADMIN_PASS_HASH`, y cambiarla desde el panel (botón "Cambiar contraseña").

### Fase 2 — cada PC hija (kiosko)

Repetir esto en **cada una** de las PCs de la sala (empezar con 2-3 antes de hacerlo en todas):

1. Copiar el repo `biblioteca_cliente` a la PC.
2. Si se usa TLS: copiar el `ca.pem` generado en la Fase 1 (paso 4) a `cliente/ca.pem` en esta PC.
3. Instalar dependencias e iniciar el asistente:
   ```bash
   cd cliente
   pip install -r requirements.txt   # o --break-system-packages si PEP 668
   python setup.py
   ```
4. En el asistente: nombre de la PC, URL del servidor (`https://<IP-PC-maestra>:8000` o `http://` solo si es a propósito), ruta al `ca.pem` copiado en el paso 2 si aplica.
5. `setup.py` genera y muestra el `PC_ID` de esta PC — **antes de continuar el asistente**, ir al panel de la PC maestra (pestaña "PCs" → "Generar API key") con ese `PC_ID` y copiar la key generada de vuelta al asistente cuando la pida (se ve una sola vez).
6. Definir el PIN de administrador del kiosko cuando se pida.
7. Aceptar instalar el autostart (`.desktop` +, recomendado, servicio `systemd`) cuando `setup.py` lo ofrezca.
8. (Producción) aplicar el bloqueo de escritorio a nivel de sistema si el compositor es GNOME — ver `docs/desarrollo/despliegue.md` de `biblioteca_cliente`, sección **Bloqueo de escritorio para producción**.

### Fase 3 — verificación y rollout

1. Con 2-3 PCs configuradas, en el panel de la PC maestra (pestaña "PCs") confirmar que cada una aparece, con heartbeat de estado y de hardware llegando, y que una sesión de prueba (login con un carnet de prueba) aparece en la pestaña "Sesiones".
2. Recién con eso confirmado, repetir la Fase 2 en el resto de las PCs de la sala.
3. (Opcional) exponer el panel fuera de la LAN vía túnel Cloudflare (`cloudflared/`, no incluido en este repo) en vez de abrir puertos hacia internet.
4. Agendar en cron de la PC maestra `backup_db.sh` (ver sección **Backups de MySQL**) y, si hay TLS, `verificar_vencimiento_cert.sh` (ver sección **TLS**).
5. Repasar el **Checklist de seguridad antes de producción** de arriba.

Guía de instalación del cliente con más detalle: ver `biblioteca_cliente/docs/desarrollo/despliegue.md`.
