from pydantic import BaseModel, Field


# Topes de longitud para no hashear con PBKDF2 cadenas arbitrariamente largas. El de
# `password_nueva` lo valida `validar_password_nueva` (routers/auth.py) con un mensaje propio;
# acá solo se acota el tamaño de lo que llega.
class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


class Token(BaseModel):
    access_token: str
    token_type: str


class CambiarPasswordRequest(BaseModel):
    password_actual: str = Field(max_length=1024)
    password_nueva: str = Field(max_length=1024)
