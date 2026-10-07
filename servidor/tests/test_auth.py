"""Tests de las piezas de auth.py con más impacto si se rompen en silencio:
verificar_password/generar_hash (hashing de contraseñas de admin),
_token_revocado (invalidación de JWT tras cambio de contraseña) y verify_token
(que las junta). No se levanta ninguna base de datos real: donde verify_token
necesita `db_admins.obtener_actualizado`, se reemplaza (monkeypatch) por un
doble de prueba."""

from datetime import datetime, timedelta

import pytest
from routers import auth

# --- verificar_password / generar_hash ---------------------------------

def test_generar_hash_y_verificar_password_hacen_roundtrip():
    hash_ = auth.generar_hash("una-contraseña-segura")
    assert auth.verificar_password("una-contraseña-segura", hash_)


def test_verificar_password_rechaza_password_incorrecta():
    hash_ = auth.generar_hash("correcta")
    assert not auth.verificar_password("incorrecta", hash_)


def test_verificar_password_rechaza_hash_malformado_o_ausente():
    assert not auth.verificar_password("cualquier-cosa", "esto-no-es-un-hash-valido")
    assert not auth.verificar_password("cualquier-cosa", None)


def test_hash_dummy_tiene_formato_y_costo_de_un_hash_real():
    # _HASH_DUMMY es lo que login() usa para verificar cuando el username no existe, así que
    # tiene que ser un hash pbkdf2_sha256 válido con las mismas iteraciones que uno real — si no,
    # verificar_password() correría más rápido/lento ahí y reabriría el canal de timing (B1).
    iteraciones, _salt, _hash_hex = auth._parsear_hash(auth._HASH_DUMMY)
    assert iteraciones == auth.PBKDF2_ITERACIONES
    assert not auth.verificar_password("cualquier-cosa", auth._HASH_DUMMY)


def test_generar_hash_usa_un_salt_distinto_cada_vez():
    # Dos hashes de la misma contraseña no deben ser iguales (protege contra
    # tablas arcoíris); ambos deben seguir verificando esa misma contraseña.
    hash_a = auth.generar_hash("misma-contraseña")
    hash_b = auth.generar_hash("misma-contraseña")
    assert hash_a != hash_b
    assert auth.verificar_password("misma-contraseña", hash_a)
    assert auth.verificar_password("misma-contraseña", hash_b)


# --- _token_revocado -----------------------------------------------------

def test_token_revocado_si_falta_sub_iat_o_jti():
    assert auth._token_revocado({}) is True
    assert auth._token_revocado({"sub": "admin"}) is True
    assert auth._token_revocado({"sub": "admin", "iat": 0}) is True


def test_token_revocado_si_el_usuario_ya_no_existe(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: None)
    payload = {"sub": "admin-borrado", "iat": 0}
    assert auth._token_revocado(payload) is True


def test_token_revocado_false_si_el_password_no_cambio_despues_del_iat(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: datetime(2000, 1, 1))
    payload = {"sub": "admin", "iat": auth.calendar.timegm(datetime(2020, 1, 1).timetuple()), "jti": "abc"}
    assert auth._token_revocado(payload) is False


def test_token_revocado_true_si_el_password_cambio_despues_del_iat(monkeypatch):
    # Simula el caso central de PUT /auth/password: el token se emitió antes
    # del cambio, así que debe quedar revocado aunque no haya expirado.
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: datetime(2020, 1, 2))
    payload = {"sub": "admin", "iat": auth.calendar.timegm(datetime(2020, 1, 1).timetuple()), "jti": "abc"}
    assert auth._token_revocado(payload) is True


def test_token_revocado_true_si_su_jti_se_dio_de_baja_en_logout(monkeypatch, tokens_revocados):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: datetime(2000, 1, 1))
    payload = {"sub": "admin", "iat": auth.calendar.timegm(datetime(2020, 1, 1).timetuple()), "jti": "abc"}
    tokens_revocados.add("abc")
    assert auth._token_revocado(payload) is True


def test_create_token_asigna_un_jti_distinto_a_cada_token():
    a = auth.jwt.decode(auth.create_token({"sub": "admin"}), auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    b = auth.jwt.decode(auth.create_token({"sub": "admin"}), auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    assert a["jti"] and b["jti"] and a["jti"] != b["jti"]


# --- verify_token ---------------------------------------------------------

def test_verify_token_rechaza_token_con_firma_invalida():
    with pytest.raises(auth.HTTPException) as exc:
        auth.verify_token("esto-no-es-un-jwt-valido")
    assert exc.value.status_code == 401


def test_verify_token_no_consulta_revocacion_para_tokens_no_admin(monkeypatch):
    # Un JWT de kiosko (role != "admin") no pasa por _token_revocado: no hay
    # "contraseña" de PC que cambiar, y consultar la BD acá sería una carga
    # innecesaria en cada request de sync/estado/hardware.
    def _falla_si_se_llama(username):
        raise AssertionError("no debería consultarse la BD para un token no-admin")

    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", _falla_si_se_llama)
    token = auth.create_token({"sub": "PC-01", "role": "kiosk"})
    payload = auth.verify_token(token)
    assert payload["sub"] == "PC-01"
    assert payload["role"] == "kiosk"


def test_verify_token_admin_ok_si_no_hubo_cambio_de_password_despues(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: datetime(2000, 1, 1))
    token = auth.create_token({"sub": "admin", "role": "admin"})
    payload = auth.verify_token(token)
    assert payload["sub"] == "admin"


def test_verify_token_admin_revocado_si_password_cambio_despues(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: datetime.utcnow() + timedelta(hours=1))
    token = auth.create_token({"sub": "admin", "role": "admin"})
    with pytest.raises(auth.HTTPException) as exc:
        auth.verify_token(token)
    assert exc.value.status_code == 401


def test_verify_token_admin_revocado_si_el_usuario_ya_no_existe(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_actualizado", lambda username: None)
    token = auth.create_token({"sub": "admin-borrado", "role": "admin"})
    with pytest.raises(auth.HTTPException):
        auth.verify_token(token)


# --- validar_password_nueva ------------------------------------------------

@pytest.mark.parametrize("password", [
    "corta",                      # menos de 12 caracteres
    "x" * 129,                    # más de 128
    "Administrador",              # igual al username (sin distinguir mayúsculas)
    "biblioteca2026",             # publicada en el historial del repo
])
def test_validar_password_nueva_rechaza(password):
    assert auth.validar_password_nueva(password, "administrador") is not None


def test_validar_password_nueva_acepta_una_contrasena_razonable():
    assert auth.validar_password_nueva("una frase larga de verdad", "admin") is None
