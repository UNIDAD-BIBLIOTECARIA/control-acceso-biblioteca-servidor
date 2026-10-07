from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .catalogo import es_combinacion_valida
from .tipos import PC_ID_PATTERN, SexoValido


class Sesion(BaseModel):
    id: str = Field(max_length=100)
    pc_id: str = Field(max_length=100, pattern=PC_ID_PATTERN)
    carnet: Optional[str] = Field(default=None, max_length=30, pattern=r"^[A-Z]{2}\d{5}$")
    hora_inicio: str = Field(max_length=32)
    hora_fin: Optional[str] = Field(default=None, max_length=32)
    fecha: str = Field(max_length=10)
    sincronizado: Optional[int] = 0
    timestamp_sync: Optional[str] = Field(default=None, max_length=32)
    nombre: Optional[str] = Field(default=None, max_length=255)
    carrera: Optional[str] = Field(default=None, max_length=255)
    facultad: Optional[str] = Field(default=None, max_length=255)
    sexo: Optional[SexoValido] = None
    fecha_nacimiento: Optional[str] = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _descartar_carrera_fuera_de_catalogo(self):
        """Una carrera/facultad fuera del catálogo no llega a la base (ni a las
        estadísticas), pero tampoco rechaza el payload: la sesión o el heartbeat
        son válidos igual, y rechazarlos por esto perdería datos de uso si un
        kiosko quedara con un catálogo distinto al del servidor."""
        if not es_combinacion_valida(self.carrera, self.facultad):
            self.carrera = None
            self.facultad = None
        return self
