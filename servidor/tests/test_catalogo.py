"""Validación de carrera/facultad contra el catálogo en los modelos que llegan
del kiosko: `Estudiante` rechaza la combinación inválida; `Sesion` y
`EstadoPayload` la descartan sin rechazar el payload."""

import pytest
from models import EstadoPayload, Estudiante, Sesion
from pydantic import ValidationError

FACULTAD = "Departamento de Ingeniería y Arquitectura"
CARRERA = "Ingeniería en Sistemas Informáticos"


def test_estudiante_acepta_combinacion_del_catalogo_o_ninguna():
    Estudiante(carnet="AB12345", nombre="X", carrera=CARRERA, facultad=FACULTAD)
    Estudiante(carnet="AB12345", nombre="X", carrera="Técnico en Veterinaria y Zootecnia", facultad="Extensión La Unión")
    Estudiante(carnet="AB12345", nombre="X")


@pytest.mark.parametrize("carrera,facultad", [
    ("Carrera inventada", FACULTAD),
    (CARRERA, "Facultad inventada"),
    (CARRERA, None),
    ("Arquitectura", "Departamento de Medicina"),  # existe, pero en otra facultad
])
def test_estudiante_rechaza_combinacion_fuera_del_catalogo(carrera, facultad):
    with pytest.raises(ValidationError):
        Estudiante(carnet="AB12345", nombre="X", carrera=carrera, facultad=facultad)


def test_sesion_descarta_carrera_fuera_del_catalogo_sin_rechazarla():
    s = Sesion(id="s1", pc_id="PC-01", carnet="AB12345", hora_inicio="2026-01-01T10:00:00",
               fecha="2026-01-01", carrera="=HYPERLINK(\"x\")", facultad=FACULTAD)
    assert s.carrera is None and s.facultad is None


def test_estado_descarta_carrera_fuera_del_catalogo_sin_rechazarlo():
    e = EstadoPayload(pc_id="PC-01", sesion_activa=True, carnet="AB12345",
                      carrera="Inventada", facultad="Inventada")
    assert e.carrera is None and e.facultad is None
    ok = EstadoPayload(pc_id="PC-01", sesion_activa=True, carrera=CARRERA, facultad=FACULTAD)
    assert ok.carrera == CARRERA
