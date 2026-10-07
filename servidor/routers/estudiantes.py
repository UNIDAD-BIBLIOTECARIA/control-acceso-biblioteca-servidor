import logging

from db import estado as db_estado
from db import estudiantes as db_estudiantes
from fastapi import APIRouter, Depends, HTTPException, Request
from models import Estudiante
from seudonimo import seudonimo

from routers.auth import (
    limitar_escrituras_kiosko,
    limitar_lecturas_estudiante,
    require_auth,
)

router = APIRouter(prefix="/estudiantes", tags=["estudiantes"])
log = logging.getLogger("uvicorn.error")


def _actor_ip(request: Request, actor: dict) -> str:
    ip = request.client.host if request.client else "desconocida"
    return f"{actor.get('sub')} ({actor.get('role')}) desde {ip}"


@router.post("", status_code=201)
def registrar_estudiante(
    est: Estudiante, request: Request, actor: dict = Depends(limitar_escrituras_kiosko)
):
    try:
        db_estudiantes.crear(est)
    except db_estudiantes.CarnetYaRegistrado:
        log.warning("Alta de estudiante %s rechazada (carnet ya registrado) — %s", seudonimo(est.carnet), _actor_ip(request, actor))
        raise HTTPException(status_code=409, detail="Carnet ya registrado") from None
    log.info("Alta de estudiante %s — %s", seudonimo(est.carnet), _actor_ip(request, actor))
    return {"carnet": est.carnet}


@router.get("", dependencies=[Depends(require_auth)])
def listar_estudiantes():
    return db_estudiantes.listar()


@router.get("/{carnet}", dependencies=[Depends(limitar_lecturas_estudiante)])
def obtener_estudiante(carnet: str):
    try:
        return db_estudiantes.obtener(carnet)
    except db_estudiantes.EstudianteNoEncontrado:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado") from None


@router.put("/{carnet}")
def actualizar_estudiante(
    carnet: str, est: Estudiante, request: Request, actor: dict = Depends(limitar_escrituras_kiosko)
):
    # El kiosko identifica al estudiante solo por el carnet, que cualquiera
    # puede teclear. Para que una API key de PC no sirva para editar fichas
    # ajenas, un kiosko solo puede editar al estudiante que tiene la sesión
    # abierta en esa misma PC según su último heartbeat. El admin no se restringe.
    if actor.get("role") == "kiosk" and not db_estado.carnet_activo_en_pc(actor.get("pc_id"), carnet):
        log.warning("Actualización de estudiante %s rechazada (sin sesión activa en la PC) — %s", seudonimo(carnet), _actor_ip(request, actor))
        raise HTTPException(
            status_code=403,
            detail="Solo se pueden editar los datos del estudiante con sesión activa en esta PC",
        )
    try:
        db_estudiantes.actualizar(carnet, est)
    except db_estudiantes.EstudianteNoEncontrado:
        log.warning("Actualización de estudiante %s rechazada (no encontrado) — %s", seudonimo(carnet), _actor_ip(request, actor))
        raise HTTPException(status_code=404, detail="Estudiante no encontrado") from None
    log.info("Actualización de estudiante %s — %s", seudonimo(carnet), _actor_ip(request, actor))
    return {"ok": True, "carnet": carnet}


@router.delete("/{carnet}", status_code=204)
def eliminar_estudiante(carnet: str, request: Request, actor: dict = Depends(require_auth)):
    try:
        db_estudiantes.eliminar(carnet)
    except db_estudiantes.EstudianteNoEncontrado:
        log.warning("Baja de estudiante %s rechazada (no encontrado) — %s", seudonimo(carnet), _actor_ip(request, actor))
        raise HTTPException(status_code=404, detail="Estudiante no encontrado") from None
    except db_estudiantes.TieneSesionesRegistradas:
        log.warning("Baja de estudiante %s rechazada (tiene sesiones registradas) — %s", seudonimo(carnet), _actor_ip(request, actor))
        raise HTTPException(status_code=409, detail="No se puede eliminar: tiene sesiones registradas") from None
    log.info("Baja de estudiante %s — %s", seudonimo(carnet), _actor_ip(request, actor))
