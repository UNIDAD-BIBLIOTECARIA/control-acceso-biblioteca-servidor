from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .catalogo import es_combinacion_valida
from .tipos import SexoValido


class Estudiante(BaseModel):
    nombre: str = Field(max_length=255)
    carnet: str = Field(max_length=30, pattern=r"^[A-Z]{2}\d{5}$")
    fecha_nacimiento: Optional[str] = Field(default=None, max_length=10)
    carrera: Optional[str] = Field(default=None, max_length=255)
    facultad: Optional[str] = Field(default=None, max_length=255)
    sexo: Optional[SexoValido] = None
    fecha_registro: Optional[str] = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _carrera_del_catalogo(self):
        if not es_combinacion_valida(self.carrera, self.facultad):
            raise ValueError("carrera y facultad deben ser una combinación del catálogo (GET /estudiantes/catalogo)")
        return self
