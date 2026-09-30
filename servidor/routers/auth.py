import calendar
import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Optional

import jwt
from contrasenas_publicadas import es_contrasena_publicada
from db import admins as db_admins
from db import pcs as db_pcs
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from models import CambiarPasswordRequest, LoginRequest, Token
from models.tipos import PC_ID_PATTERN

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("uvicorn.error")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(
            f"La variable de entorno {name} es obligatoria y no puede estar vacía. "
            f"Configúrala en tu .env antes de iniciar el servidor."
        )
    return value


def _parsear_hash(hash_almacenado: str) -> tuple[int, bytes, str]:
    """Descompone un hash `pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>`. Lanza ValueError si
    el formato no es válido (algoritmo distinto, número de campos incorrecto, hex inválido, etc.)."""
    algoritmo, iteraciones_s, salt_hex, hash_hex = hash_almacenado.split("$")
    if algoritmo != "pbkdf2_sha256":
        raise ValueError(f"algoritmo desconocido: {algoritmo}")
    return int(iteraciones_s), bytes.fromhex(salt_hex), hash_hex


def verificar_password(password: str, hash_almacenado: str) -> bool:
    """Verifica `password` contra un hash generado con `generar_hash()` (o con el script
    standalone `servidor/generar_hash_admin.py`). Nunca compara contraseñas en texto plano:
    así ni el `.env` ni la base de datos guardan la contraseña real, solo su hash."""
    try:
        iteraciones, salt, hash_hex = _parsear_hash(hash_almacenado)
    except (ValueError, AttributeError):
        return False
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iteraciones)
    return hmac.compare_digest(derivado.hex(), hash_hex)


PBKDF2_ITERACIONES = 600_000  # recomendación OWASP (2023+) para PBKDF2-HMAC-SHA256


def generar_hash(password: str) -> str:
    """Genera un hash `pbkdf2_sha256$<iteraciones>$<salt_hex>$<hash_hex>` para guardar en la
    tabla `admins`. Usado por `PUT /auth/password`; el script `generar_hash_admin.py` tiene su
    propia copia de esta lógica porque corre standalone, fuera del paquete de la app."""
    salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERACIONES)
    return f"pbkdf2_sha256${PBKDF2_ITERACIONES}${salt.hex()}${derivado.hex()}"


# Hash "señuelo" contra el que se verifica en login() cuando el username no existe, para que
# ese caso corra igual el PBKDF2 completo (mismas iteraciones) que uno con username real y
# contraseña incorrecta. Sin esto, "usuario no existe" corta antes de calcular el PBKDF2 y
# responde medibles milisegundos antes que "contraseña incorrecta" — un atacante puede usar esa
# diferencia de tiempo para enumerar qué usuarios de admin existen. Se calcula una sola vez al
# importar el módulo (no en cada request) porque el hash en sí es irrelevante, solo importa que
# tenga el formato/costo de uno real.
_HASH_DUMMY = generar_hash(secrets.token_hex(16))


SECRET_KEY = _require_env("SECRET_KEY")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = int(os.environ.get("TOKEN_EXPIRE_HOURS") or 24)

KIOSK_API_KEY = os.environ.get("KIOSK_API_KEY", "")

# Tipo para el `pc_id` recibido como segmento de URL (`/pcs/{pc_id}/...`,
# `/pcs/{pc_id}/hardware`) — mismo `PC_ID_PATTERN` que ya validan los payloads
# de estado/sync/hardware (ver models/tipos.py). Antes de esto un pc_id con
# saltos de línea llegaba tal cual hasta los logs de routers/pcs.py; con el
# patrón, FastAPI rechaza esa URL con 422 antes de que el endpoint corra.
PcId = Annotated[str, Path(pattern=PC_ID_PATTERN)]

# El panel se sirve por HTTPS si este proceso termina TLS él mismo (`TLS_CERT_PATH`/
# `TLS_KEY_PATH`) o si lo termina un proxy/túnel delante (`BEHIND_HTTPS_PROXY`, p. ej.
# Cloudflare Tunnel: el navegador habla HTTPS con Cloudflare pero a este proceso le llega
# HTTP plano, así que sin esta variable no habría forma de saberlo desde acá). Decide si la
# cookie de sesión del panel (`_set_auth_cookies`) lleva `Secure` y si
# `SecurityHeadersMiddleware` (`main.py`) manda HSTS — sin eso, la cookie del admin viajaría
# en claro si el navegador llega a pedir `http://` al dominio público.
_TLS_PROPIO = bool(os.environ.get("TLS_CERT_PATH")) and bool(os.environ.get("TLS_KEY_PATH"))
_HTTPS_POR_PROXY = os.environ.get("BEHIND_HTTPS_PROXY", "").strip().lower() in ("1", "true", "yes")
HTTPS_ACTIVO = _TLS_PROPIO or _HTTPS_POR_PROXY

# Métodos que cambian estado: los únicos donde `_verificar_csrf` exige el header
# X-CSRF-Token cuando la autenticación vino de la cookie del panel (ver más abajo).
_METODOS_MUTANTES = {"POST", "PUT", "PATCH", "DELETE"}


def generar_api_key() -> str:
    """Genera una API key nueva para una PC (`POST /pcs/{pc_id}/api-key`).
    Alta entropía por construcción (256 bits de `secrets`), a diferencia de
    una contraseña elegida por una persona."""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Hash de una API key de PC para guardar en `pcs.api_key_hash`. A
    diferencia de `generar_hash()` (PBKDF2, 600k iteraciones, pensado para
    contraseñas de baja entropía elegidas por una persona), esta key la
    genera siempre el propio servidor con suficiente entropía como para que
    un hash simple sea seguro contra fuerza bruta — no hace falta pagar el
    costo de cómputo de PBKDF2 en cada request de los kioskos."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

LOGIN_MAX_INTENTOS = int(os.environ.get("LOGIN_MAX_INTENTOS") or 5)
LOGIN_BLOQUEO_SEGUNDOS = int(os.environ.get("LOGIN_BLOQUEO_MINUTOS") or 15) * 60

# IPs de proxies/túneles de confianza (p. ej. Cloudflare Tunnel) que pueden añadir al final
# de X-Forwarded-For la IP real del cliente. Sin esto, cualquier cliente podría falsificar
# el header para esquivar el rate limit, así que por defecto (lista vacía) nunca se confía
# en él y se usa siempre la IP de la conexión TCP directa.
TRUSTED_PROXIES = {ip.strip() for ip in os.environ.get("TRUSTED_PROXIES", "").split(",") if ip.strip()}

# Los tres contadores de rate limiting de este módulo (_intentos_fallidos acá abajo,
# _lecturas_estudiante y _escrituras_kiosko más adelante) viven en memoria del proceso, no en
# un almacén compartido (Redis, la propia BD, etc.). Repartidos entre varios workers/réplicas
# de uvicorn, cada uno llevaría su propio contador y un atacante podría repartir sus intentos
# entre ellos para esquivar el límite. Mientras el despliegue corra un solo proceso de uvicorn
# (el caso actual, ver docker-entrypoint.sh y docs/desarrollo/despliegue.md) esto no aplica; si
# alguna vez hace falta escalar a más de un worker o réplica, este estado tiene que migrar
# primero a un almacén compartido entre procesos.
_intentos_fallidos: dict[str, dict] = {}

_lecturas_estudiante: dict[str, list[float]] = {}
LECTURAS_ESTUDIANTE_MAX_POR_MINUTO = int(os.environ.get("ESTUDIANTES_MAX_LECTURAS_MIN") or 30)


def _client_ip(request: Request) -> str:
    """IP real del cliente para el rate limiting de login. Si la conexión TCP directa viene
    de una IP listada en TRUSTED_PROXIES, se recorre X-Forwarded-For de derecha a izquierda
    saltando los proxies de confianza y se usa la primera IP que no lo sea; si no, se usa
    la IP directa. Evita que, detrás de un reverse proxy o túnel no configurado como
    confiable, todas las conexiones legítimas compartan una sola IP y un atacante bloquee a
    todos los administradores con un único origen.

    No se usa el primer valor del header: los proxies (Cloudflare incluido) *añaden* la IP
    que ven al final de un X-Forwarded-For que ya puede traer el cliente, así que todo lo
    que queda a la izquierda de la última IP añadida por un proxy de confianza lo controla
    el atacante, y bastaría con cambiarlo en cada intento para esquivar el bloqueo."""
    directa = request.client.host if request.client else "desconocida"
    if directa not in TRUSTED_PROXIES:
        return directa
    xff = request.headers.get("X-Forwarded-For", "")
    ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
    for ip in reversed(ips):
        if ip not in TRUSTED_PROXIES:
            return ip
    return directa


def _purgar_intentos_expirados() -> None:
    """Elimina entradas de `_intentos_fallidos` cuyo bloqueo ya expiró y cuyo último intento
    fallido es más viejo que la ventana de bloqueo. Sin esto, una IP que falla unas pocas
    veces (por debajo del umbral) y no vuelve a intentar queda en el dict para siempre —
    fuga de memoria lenta en despliegues de larga duración."""
    ahora = time.time()
    expiradas = [
        ip
        for ip, entrada in _intentos_fallidos.items()
        if entrada["bloqueado_hasta"] < ahora and (ahora - entrada["ultimo_intento"]) > LOGIN_BLOQUEO_SEGUNDOS
    ]
    for ip in expiradas:
        _intentos_fallidos.pop(ip, None)


def _segundos_bloqueado(ip: str) -> Optional[int]:
    """Devuelve los segundos restantes de bloqueo para `ip`, o None si puede intentar login.
    Si el bloqueo ya expiró, limpia el registro (nueva ventana de intentos desde cero)."""
    entrada = _intentos_fallidos.get(ip)
    if not entrada:
        return None
    restante = entrada["bloqueado_hasta"] - time.time()
    if restante > 0:
        return int(restante) + 1
    if entrada["bloqueado_hasta"]:
        _intentos_fallidos.pop(ip, None)
    return None


def _registrar_intento_fallido(ip: str) -> None:
    entrada = _intentos_fallidos.setdefault(ip, {"fallos": 0, "bloqueado_hasta": 0.0, "ultimo_intento": 0.0})
    entrada["fallos"] += 1
    entrada["ultimo_intento"] = time.time()
    log.warning("Login fallido desde %s (intento %d/%d)", ip, entrada["fallos"], LOGIN_MAX_INTENTOS)
    if entrada["fallos"] >= LOGIN_MAX_INTENTOS:
        entrada["bloqueado_hasta"] = time.time() + LOGIN_BLOQUEO_SEGUNDOS
        log.warning("IP %s bloqueada por %d minutos tras exceder intentos de login", ip, LOGIN_BLOQUEO_SEGUNDOS // 60)


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["iat"] = datetime.utcnow()
    payload["jti"] = secrets.token_urlsafe(16)
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _token_revocado(payload: dict) -> bool:
    """Un JWT de admin (`role: admin`) queda revocado si se emitió (`iat`) antes del último
    cambio de contraseña de ese usuario, o si el usuario ya no existe. Sin esto, cambiar la
    contraseña (`PUT /auth/password`) no servía para nada si el token viejo ya se había
    filtrado (XSS, malware, red sin TLS): seguía siendo válido hasta que expirara solo, sin
    importar la contraseña nueva. Compara siempre en UTC calculado en Python (ver
    `db/admins.py::actualizar_password`) para no depender de la zona horaria del servidor
    de MySQL.

    También queda revocado si su `jti` se dio de baja en `POST /auth/logout`: sin eso,
    cerrar sesión solo borraba las cookies del navegador y una copia del token (el Bearer
    de un script, o una cookie robada antes) seguía valiendo hasta su `exp`."""
    username = payload.get("sub")
    emitido = payload.get("iat")
    jti = payload.get("jti")
    if username is None or emitido is None or jti is None:
        return True
    actualizado = db_admins.obtener_actualizado(username)
    if actualizado is None:
        return True  # el admin ya no existe (o nunca existió)
    if emitido < calendar.timegm(actualizado.timetuple()):
        return True
    return db_admins.jti_revocado(jti)


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from None
    if payload.get("role") == "admin" and _token_revocado(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión cerrada o invalidada, inicia sesión de nuevo",
        )
    return payload


_bearer_scheme = HTTPBearer(auto_error=False)


def _set_auth_cookies(response: Response, token: str, csrf_token: str) -> None:
    """Guarda la sesión del panel admin en dos cookies en vez del JWT plano que el panel
    históricamente devolvía en el JSON de `/auth/login` para que el propio JS lo guardara en
    `sessionStorage` (ver `panel/js/api.js`) — cualquier XSS futuro en el panel podía leerlo
    de ahí y robar la sesión completa. `access_token` es `HttpOnly` (inalcanzable desde JS);
    `csrf_token` no lo es, porque el panel sí necesita leerla para reenviarla como header en
    escrituras (ver `_verificar_csrf`) — no es sensible por sí sola, solo sirve junto con la
    cookie HttpOnly. `SameSite=Strict` porque el panel nunca necesita que viaje en un request
    de origen distinto; `Secure` según `HTTPS_ACTIVO`."""
    max_age = TOKEN_EXPIRE_HOURS * 3600
    response.set_cookie("access_token", token, httponly=True, secure=HTTPS_ACTIVO,
                         samesite="strict", max_age=max_age, path="/")
    response.set_cookie("csrf_token", csrf_token, httponly=False, secure=HTTPS_ACTIVO,
                         samesite="strict", max_age=max_age, path="/")


def _verificar_csrf(request: Request, payload: dict) -> None:
    """Si la autenticación de este request vino de la cookie `access_token` (no de un header
    `Authorization: Bearer`, que un navegador nunca adjunta solo — eso lo hace a mano el JS
    del panel o un script), el navegador manda la cookie automáticamente en cualquier
    request, incluido uno de origen cruzado. `SameSite=Strict` ya bloquea eso en navegadores
    actuales, pero como defensa en profundidad se exige además, en métodos que cambian
    estado, un header `X-CSRF-Token` igual al claim `csrf` firmado dentro del propio JWT
    (patrón doble-submit: no hace falta guardar nada extra en el servidor — alcanza con que
    el mismo valor también viaje en la cookie legible `csrf_token` y el panel la reenvíe)."""
    if request.method not in _METODOS_MUTANTES:
        return
    header_csrf = request.headers.get("X-CSRF-Token", "")
    if not header_csrf or not hmac.compare_digest(header_csrf, payload.get("csrf", "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido o ausente")


def _autenticar_admin(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> dict:
    """Verifica un JWT de admin llegado por `Authorization: Bearer` (scripts/API — no exige
    CSRF, un navegador nunca lo adjunta por su cuenta) o por la cookie `access_token` del
    panel web (sí exige CSRF vía `_verificar_csrf`)."""
    if credentials is not None:
        return verify_token(credentials.credentials)
    token = request.cookies.get("access_token")
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token requerido")
    payload = verify_token(token)
    _verificar_csrf(request, payload)
    return payload


def require_auth(request: Request, credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> dict:
    """Dependencia FastAPI: exige un JWT de admin válido por `Authorization: Bearer` o por la
    cookie `access_token` (panel web) — 401 si falta o no verifica."""
    return _autenticar_admin(request, credentials)


def require_kiosk_or_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    x_kiosk_key: Optional[str] = Header(None, alias="X-Kiosk-Key"),
    x_pc_id: Optional[str] = Header(None, alias="X-PC-Id", pattern=PC_ID_PATTERN),
) -> dict:
    """Dependencia FastAPI: acepta JWT de admin (`Authorization: Bearer` o la cookie
    `access_token` del panel) o la API key de kiosko (`X-Kiosk-Key`). La key de kiosko es
    por PC: el cliente manda también `X-PC-Id` y se valida contra el hash guardado en
    `pcs.api_key_hash` para esa PC (generado desde el panel con `POST /pcs/{pc_id}/api-key`),
    así una key filtrada de un equipo se puede revocar (`DELETE /pcs/{pc_id}/api-key`) sin
    afectar a los demás y el `sub` del actor identifica a la PC real, no una etiqueta
    genérica.

    Solo si la PC de `X-PC-Id` **no** tiene key propia configurada se compara contra la
    `KIOSK_API_KEY` compartida (`.env`), como vía de compatibilidad para equipos que
    todavía no se migraron a una key propia. Una PC que ya tiene key propia solo acepta
    esa key: si no, la clave compartida seguiría abriendo la PC después de revocar o rotar
    su key. La vía compartida también exige `X-PC-Id` y devuelve un actor con ese `pc_id`,
    así `verificar_pc_id` le impide escribir datos de otras PCs y el rate limit se cuenta
    por PC. Si `KIOSK_API_KEY` no está configurada, esa vía queda siempre cerrada (nunca
    cae a un valor por defecto adivinable)."""
    if x_kiosk_key and x_pc_id:
        api_key_hash = db_pcs.obtener_api_key_hash(x_pc_id)
        if api_key_hash:
            if hmac.compare_digest(hash_api_key(x_kiosk_key), api_key_hash):
                return {"sub": x_pc_id, "role": "kiosk", "pc_id": x_pc_id}
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida para esta PC")
        if KIOSK_API_KEY and hmac.compare_digest(x_kiosk_key, KIOSK_API_KEY):
            log.warning(
                "Kiosko %s autenticado con la API key compartida (sin key propia configurada). "
                "Generar una key dedicada desde el panel (POST /pcs/{pc_id}/api-key).",
                x_pc_id,
            )
            return {"sub": x_pc_id, "role": "kiosk", "pc_id": x_pc_id}
    if credentials is not None or "access_token" in request.cookies:
        return _autenticar_admin(request, credentials)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Se requiere JWT de admin o API key de kiosko")


def verificar_pc_id(actor: dict, pc_id: str) -> None:
    """Si el actor es un kiosko (con su API key propia o con la KIOSK_API_KEY
    compartida, que también queda atada al `X-PC-Id`), solo puede escribir
    datos para esa misma PC. Sin esto, cualquier PC puede suplantar el
    estado/sesiones/hardware de cualquier otra. Un JWT de admin no se restringe."""
    if actor.get("role") == "kiosk" and actor.get("pc_id") and actor["pc_id"] != pc_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La API key de esta PC no autoriza a reportar datos de otra PC",
        )


def _purgar_lecturas_expiradas() -> None:
    """Elimina de `_lecturas_estudiante` las claves sin consultas en la última ventana de 60s.
    Mismo propósito que `_purgar_intentos_expirados`: sin esto el dict crece sin límite en
    despliegues de larga duración (aunque acá el radio es chico, un puñado de kioskos)."""
    ahora = time.time()
    vacias = [clave for clave, ventana in _lecturas_estudiante.items() if not ventana or ahora - ventana[-1] > 60]
    for clave in vacias:
        _lecturas_estudiante.pop(clave, None)


def limitar_lecturas_estudiante(request: Request, actor: dict = Depends(require_kiosk_or_admin)) -> dict:
    """Dependencia FastAPI: exige JWT de admin o `X-Kiosk-Key` (igual que `require_kiosk_or_admin`)
    y además limita cuántas veces por minuto se puede consultar `GET /estudiantes/{carnet}` con la
    key de kiosko. Se limita por la credencial (`actor["sub"]`: el `pc_id`, tanto con key propia
    como con la `KIOSK_API_KEY` compartida) y no por IP — así una key filtrada
    reproducida desde varias IPs (proxies, redes distintas) no evade el límite repartiendo las
    consultas entre orígenes; solo si no hay actor identificable se cae a la IP como respaldo. Sin
    este límite, cualquiera con la key podría barrer el espacio de carnets y extraer los datos de
    toda la población estudiantil sin fricción. El panel admin (JWT, login individual) queda exento."""
    if actor.get("role") == "admin":
        return actor
    clave = actor.get("sub") or _client_ip(request)
    _purgar_lecturas_expiradas()
    ahora = time.time()
    ventana = _lecturas_estudiante.setdefault(clave, [])
    ventana[:] = [t for t in ventana if ahora - t < 60]
    if len(ventana) >= LECTURAS_ESTUDIANTE_MAX_POR_MINUTO:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas consultas de estudiantes, espera un momento.",
        )
    ventana.append(ahora)
    return actor


_escrituras_kiosko: dict[str, list[float]] = {}
KIOSKO_MAX_ESCRITURAS_MIN = int(os.environ.get("KIOSKO_MAX_ESCRITURAS_MIN") or 60)


def _purgar_escrituras_expiradas() -> None:
    """Elimina de `_escrituras_kiosko` las claves sin escrituras en la última ventana de 60s.
    Mismo propósito que `_purgar_lecturas_expiradas`."""
    ahora = time.time()
    vacias = [clave for clave, ventana in _escrituras_kiosko.items() if not ventana or ahora - ventana[-1] > 60]
    for clave in vacias:
        _escrituras_kiosko.pop(clave, None)


def limitar_escrituras_kiosko(request: Request, actor: dict = Depends(require_kiosk_or_admin)) -> dict:
    """Dependencia FastAPI: igual que `limitar_lecturas_estudiante` pero para los endpoints de
    escritura autenticados con `X-Kiosk-Key` (alta/edición de estudiantes, `/sync`, `/estado`,
    `/pcs/{id}/hardware`). Se limita por la credencial (`actor["sub"]`), no por IP — ver el
    docstring de `limitar_lecturas_estudiante` para el razonamiento. Sin este límite cualquiera
    con la key podría sobrescribir en masa los datos de todos los estudiantes sin fricción.
    El panel admin (JWT, login individual) queda exento."""
    if actor.get("role") == "admin":
        return actor
    clave = actor.get("sub") or _client_ip(request)
    _purgar_escrituras_expiradas()
    ahora = time.time()
    ventana = _escrituras_kiosko.setdefault(clave, [])
    ventana[:] = [t for t in ventana if ahora - t < 60]
    if len(ventana) >= KIOSKO_MAX_ESCRITURAS_MIN:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas escrituras, espera un momento.",
        )
    ventana.append(ahora)
    return actor


def cobrar_escrituras_kiosko(request: Request, actor: dict, cantidad: int) -> None:
    """Suma `cantidad` escrituras extra a la ventana de `limitar_escrituras_kiosko` para esta
    credencial. `limitar_escrituras_kiosko` cuenta requests, pero un solo `POST /sync` puede dar
    de alta muchos estudiantes; sin este cobro, el límite por minuto no acotaría cuántas fichas
    puede crear una key filtrada. Se cobra después de procesar el request (no se rechaza el lote
    en curso, para que un kiosko con muchas sesiones acumuladas sin red no quede bloqueado para
    siempre) y el exceso frena los requests siguientes hasta que expire la ventana."""
    if actor.get("role") == "admin" or cantidad <= 0:
        return
    clave = actor.get("sub") or _client_ip(request)
    ahora = time.time()
    _escrituras_kiosko.setdefault(clave, []).extend([ahora] * cantidad)


@router.post("/login", response_model=Token)
def login(req: LoginRequest, request: Request, response: Response):
    # A diferencia de limitar_lecturas_estudiante/limitar_escrituras_kiosko, acá todavía no hay
    # actor autenticado en el momento de contar el intento — es justo lo que este endpoint está
    # evaluando — así que el límite sigue atado a la IP. Riesgo aceptado: credenciales de admin
    # filtradas y reproducidas desde varias IPs evaden este límite; no hay forma de atarlo a la
    # credencial sin conocerla de antemano.
    ip = _client_ip(request)
    _purgar_intentos_expirados()

    restante = _segundos_bloqueado(ip)
    if restante is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Intenta de nuevo en {restante // 60 + 1} minuto(s).",
            headers={"Retry-After": str(restante)},
        )

    hash_almacenado = db_admins.obtener_hash(req.username)
    # Se verifica siempre contra un hash (el real o, si el username no existe, _HASH_DUMMY) para
    # que el PBKDF2 completo corra en ambos casos — ver el docstring de _HASH_DUMMY.
    password_ok = verificar_password(req.password, hash_almacenado or _HASH_DUMMY)
    if hash_almacenado is None or not password_ok:
        _registrar_intento_fallido(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    _intentos_fallidos.pop(ip, None)
    csrf_token = secrets.token_urlsafe(32)
    token = create_token({"sub": req.username, "role": "admin", "csrf": csrf_token})
    # El panel ya no guarda este JSON en sessionStorage (ver M3 en el histórico de auditorías
    # y panel/js/api.js): la sesión real vive en las cookies que setea `_set_auth_cookies`.
    # El cuerpo se conserva igual por compatibilidad con clientes no-navegador (scripts/API
    # que autentican con `Authorization: Bearer`, documentados en README.md).
    _set_auth_cookies(response, token, csrf_token)
    # "bearer" es el token_type de OAuth2, no una contraseña.
    return Token(access_token=token, token_type="bearer")  # nosec B106


def _revocar_token(token: str) -> None:
    """Da de baja el `jti` de `token` hasta su `exp`. Si el token no verifica (firma mala,
    ya expirado) no hay nada que revocar: tampoco lo aceptaría `verify_token`."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return
    jti, exp = payload.get("jti"), payload.get("exp")
    if payload.get("role") != "admin" or jti is None or exp is None:
        return
    expira = datetime.fromtimestamp(exp, UTC).replace(tzinfo=None)
    db_admins.revocar_token(jti, expira)


@router.post("/logout")
def logout(request: Request, response: Response,
           credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)):
    """Revoca en el servidor el JWT con el que se llama (por `Authorization: Bearer` o por la
    cookie `access_token`) y limpia las cookies de sesión del panel. Borrar solo las cookies
    no bastaba: el token seguía siendo válido hasta su `exp` para quien tuviera una copia.

    No exige estar autenticado ni un `X-CSRF-Token` válido: en el peor caso un logout forzado
    por CSRF solo cierra una sesión ajena, no compromete ni expone nada, así que no vale la
    pena la fricción adicional acá."""
    token = credentials.credentials if credentials is not None else request.cookies.get("access_token")
    if token:
        _revocar_token(token)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}


@router.get("/me")
def me(usuario: dict = Depends(require_auth)):
    """Usado por el panel al cargar la página para saber si la sesión (cookie `access_token`,
    `HttpOnly` y por lo tanto ilegible desde JS) sigue siendo válida, y así decidir si mostrar
    el panel o la pantalla de login — reemplaza la comprobación que antes hacía leyendo
    `sessionStorage` directamente en el cliente."""
    return {"username": usuario.get("sub")}


@router.put("/password", response_model=Token)
def cambiar_password(req: CambiarPasswordRequest, response: Response, usuario: dict = Depends(require_auth)):
    """Permite al administrador ya autenticado cambiar su propia contraseña. Así quien
    despliega la app puede fijar unas credenciales iniciales (`ADMIN_USER`/`ADMIN_PASS_HASH`
    en el `.env`, ver `db/schema.py`) sin que sean las que se usan a largo plazo: el
    administrador real las cambia acá después de su primer login, y desde ese momento el
    `.env` queda obsoleto — las credenciales viven solo en la base de datos.

    El cambio de contraseña revoca (vía `verify_token`/`_token_revocado`) cualquier JWT
    emitido antes de este momento, incluido el que se usó para autenticar esta misma
    petición — por eso se emite acá un token nuevo (y se reescriben las cookies con
    `_set_auth_cookies`) para que la sesión actual del panel pueda seguir sin forzar un
    re-login inmediato; cualquier otra sesión con el token viejo (robada o no) sí queda
    cerrada en su próxima petición."""
    username = usuario["sub"]
    hash_almacenado = db_admins.obtener_hash(username)
    if hash_almacenado is None or not verificar_password(req.password_actual, hash_almacenado):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña actual incorrecta")
    if len(req.password_nueva) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La nueva contraseña debe tener al menos 8 caracteres",
        )
    if es_contrasena_publicada(req.password_nueva):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Esa contraseña está publicada en el repositorio del proyecto; elegí otra",
        )
    db_admins.actualizar_password(username, generar_hash(req.password_nueva))
    log.info("Contraseña de administrador '%s' actualizada", username)
    csrf_token = secrets.token_urlsafe(32)
    token = create_token({"sub": username, "role": "admin", "csrf": csrf_token})
    _set_auth_cookies(response, token, csrf_token)
    # "bearer" es el token_type de OAuth2, no una contraseña.
    return Token(access_token=token, token_type="bearer")  # nosec B106
