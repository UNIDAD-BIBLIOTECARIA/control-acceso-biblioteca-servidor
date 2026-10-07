import logging
import os
from contextlib import asynccontextmanager

from db import connection as db_connection
from db import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from observabilidad import MetricsMiddleware, metrics_payload
from routers import auth, estado, estudiantes, hardware, pcs, reportes, sync
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger(__name__)

ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", "").strip().lower() in ("1", "true", "yes")
# GET /metrics (Prometheus) -- apagado por defecto, igual que ENABLE_API_DOCS:
# no hay motivo para exponer tráfico/latencias del servicio a quien no lo pidió.
ENABLE_METRICS = os.environ.get("ENABLE_METRICS", "").strip().lower() in ("1", "true", "yes")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Biblioteca Control",
    version="1.0.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)

CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
MAX_BODY_SIZE_BYTES = int(os.environ.get("MAX_BODY_SIZE_BYTES") or 5_000_000)


class LimitBodySizeMiddleware(BaseHTTPMiddleware):
    """Rechaza requests con body antes de que FastAPI/Pydantic los procesen.

    Un request sin `Content-Length` ni `Transfer-Encoding` no tiene body
    (p. ej. `POST /pcs/{id}/mantenimiento`, que el panel llama sin body) y se
    deja pasar. Si declara `Transfer-Encoding: chunked` sin `Content-Length`
    se rechaza (411): no hay forma barata de acotar su tamaño sin leerlo
    completo, y permitirlo abriría el mismo bypass que este middleware busca
    cerrar. Con `Content-Length` presente, se compara contra
    `MAX_BODY_SIZE_BYTES` sin necesidad de leer el body completo en memoria.
    """

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length is None:
                if request.headers.get("transfer-encoding") is not None:
                    return Response("Content-Length requerido", status_code=411)
            elif int(content_length) > MAX_BODY_SIZE_BYTES:
                return Response("Payload demasiado grande", status_code=413)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Cabeceras de defensa en profundidad para el panel admin.

    El panel solo carga scripts propios (`/panel/js/*.js`, mismo origen) más
    Chart.js desde `cdn.jsdelivr.net` con SRI — de ahí el `script-src`
    acotado a esos dos orígenes. No hay estilos ni scripts inline en
    `panel/index.html`/`*.js` (todo `element.textContent`/`escapeHtml()`),
    así que no hace falta `'unsafe-inline'` en ningún directiva.
    HSTS solo se envía si el panel se sirve por HTTPS, sea porque el
    propio proceso tiene TLS habilitado (`TLS_CERT_PATH`/`TLS_KEY_PATH`)
    o porque lo termina un proxy delante (`BEHIND_HTTPS_PROXY`) — ver
    `auth.HTTPS_ACTIVO`. Anunciarlo sirviendo HTTP plano sería una
    promesa falsa al navegador.
    """

    _CSP = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    # El panel no usa cámara/micrófono/geolocalización/etc. — se deshabilitan
    # todas para que un script inyectado (compromiso del CDN de Chart.js,
    # por ejemplo) no pueda ni intentar pedir acceso a ninguna.
    _PERMISSIONS_POLICY = (
        "camera=(), microphone=(), geolocation=(), usb=(), payment=(), "
        "accelerometer=(), gyroscope=(), magnetometer=()"
    )

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = self._CSP
        response.headers["Permissions-Policy"] = self._PERMISSIONS_POLICY
        if auth.HTTPS_ACTIVO:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LimitBodySizeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if ENABLE_METRICS:
    # Agregada al final (= la más externa del stack, ver orden de
    # add_middleware de Starlette) para medir el tiempo de request completo,
    # CORS/LimitBodySize/SecurityHeaders incluidos.
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics")
    def metrics():
        cuerpo, content_type = metrics_payload()
        return Response(cuerpo, media_type=content_type)

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(estudiantes.router)
app.include_router(reportes.router)
app.include_router(estado.router)
app.include_router(pcs.router)
app.include_router(hardware.router)

panel_path = os.path.join(os.path.dirname(__file__), "panel")
if os.path.isdir(panel_path):
    app.mount("/panel", StaticFiles(directory=panel_path, html=True), name="panel")

    @app.get("/")
    def root():
        return FileResponse(os.path.join(panel_path, "index.html"))


@app.get("/health")
def health():
    """Liveness: solo dice que uvicorn responde. El kiosko la usa para saber si
    hay red con el servidor, así que no depende de MySQL."""
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    """Readiness: además comprueba que MySQL responde. La usa el HEALTHCHECK del
    contenedor, para que un MySQL colgado marque el servicio como unhealthy en
    vez de dejarlo "healthy" mientras todas las demás rutas fallan."""
    try:
        db_connection.ping()
    except Exception:
        log.exception("Health check: la base de datos no responde")
        return JSONResponse({"status": "error", "db": "unavailable"}, status_code=503)
    return {"status": "ok", "db": "ok"}
