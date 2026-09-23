"""Tests de los tres limitadores de tasa de `routers/auth.py`: el bloqueo de
intentos fallidos de `POST /auth/login` (por IP) y `limitar_lecturas_estudiante`
/ `limitar_escrituras_kiosko` (por credencial de kiosko, con IP como respaldo
solo si no hay credencial). Los tres se llaman directamente como funciones de
Python (igual que test_auth.py), sin base de datos real ni TestClient — los
contadores se limpian entre tests vía el fixture autouse de conftest.py."""

import time

import pytest
from _helpers import make_request
from fastapi import HTTPException, Response
from models import LoginRequest
from routers import auth

# --- POST /auth/login: bloqueo por IP tras demasiados fallos -------------

def test_login_bloquea_ip_tras_max_intentos_fallidos(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_hash", lambda username: None)
    req = LoginRequest(username="nadie", password="x")

    for _ in range(auth.LOGIN_MAX_INTENTOS):
        with pytest.raises(HTTPException) as exc:
            auth.login(req, make_request(ip="203.0.113.1"), Response())
        assert exc.value.status_code == 401

    # El siguiente intento, aunque las credenciales fueran correctas, ni
    # siquiera llega a verificarse: la IP ya está bloqueada.
    with pytest.raises(HTTPException) as exc:
        auth.login(req, make_request(ip="203.0.113.1"), Response())
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_login_no_bloquea_una_ip_por_los_fallos_de_otra(monkeypatch):
    monkeypatch.setattr(auth.db_admins, "obtener_hash", lambda username: None)
    req = LoginRequest(username="nadie", password="x")

    for _ in range(auth.LOGIN_MAX_INTENTOS):
        with pytest.raises(HTTPException):
            auth.login(req, make_request(ip="203.0.113.1"), Response())

    # Otra IP sigue pudiendo intentar (401 por credenciales, no 429 por bloqueo).
    with pytest.raises(HTTPException) as exc:
        auth.login(req, make_request(ip="203.0.113.2"), Response())
    assert exc.value.status_code == 401


def test_login_resetea_el_contador_tras_un_intento_exitoso(monkeypatch):
    hash_real = auth.generar_hash("clave-correcta")
    monkeypatch.setattr(auth.db_admins, "obtener_hash", lambda username: hash_real)
    ip = "203.0.113.3"

    for _ in range(auth.LOGIN_MAX_INTENTOS - 1):
        with pytest.raises(HTTPException) as exc:
            auth.login(LoginRequest(username="admin", password="incorrecta"), make_request(ip=ip), Response())
        assert exc.value.status_code == 401

    # Un login correcto limpia el contador de esa IP...
    auth.login(LoginRequest(username="admin", password="clave-correcta"), make_request(ip=ip), Response())
    assert ip not in auth._intentos_fallidos

    # ...así que hace falta agotar el máximo completo otra vez para bloquearla
    # (si el contador no se hubiera limpiado, un solo fallo más bastaría).
    for _ in range(auth.LOGIN_MAX_INTENTOS - 1):
        with pytest.raises(HTTPException) as exc:
            auth.login(LoginRequest(username="admin", password="incorrecta"), make_request(ip=ip), Response())
        assert exc.value.status_code == 401
    assert ip in auth._intentos_fallidos


def test_purgar_intentos_expirados_libera_memoria_tras_bloqueo_vencido():
    ahora = time.time()
    auth._intentos_fallidos["203.0.113.9"] = {
        "fallos": auth.LOGIN_MAX_INTENTOS,
        "bloqueado_hasta": ahora - 1,  # el bloqueo ya venció
        "ultimo_intento": ahora - auth.LOGIN_BLOQUEO_SEGUNDOS - 1,  # y hace rato que no reintenta
    }
    auth._purgar_intentos_expirados()
    assert "203.0.113.9" not in auth._intentos_fallidos


def test_purgar_intentos_expirados_no_borra_un_bloqueo_todavia_vigente():
    ahora = time.time()
    auth._intentos_fallidos["203.0.113.11"] = {
        "fallos": auth.LOGIN_MAX_INTENTOS,
        "bloqueado_hasta": ahora + 60,
        "ultimo_intento": ahora,
    }
    auth._purgar_intentos_expirados()
    assert "203.0.113.11" in auth._intentos_fallidos


# --- _client_ip ------------------------------------------------------------

_PROXY = "127.0.0.1"


def test_client_ip_ignora_xff_si_la_conexion_no_viene_de_un_proxy_de_confianza(monkeypatch):
    monkeypatch.setattr(auth, "TRUSTED_PROXIES", {_PROXY})
    request = make_request(ip="203.0.113.5", headers={"X-Forwarded-For": "198.51.100.1"})
    assert auth._client_ip(request) == "203.0.113.5"


def test_client_ip_usa_la_ip_que_anade_el_proxy_y_no_la_que_manda_el_cliente(monkeypatch):
    # El proxy añade la IP real al final de un X-Forwarded-For que ya trae el
    # cliente: el primer valor es falsificable, el último es el fiable.
    monkeypatch.setattr(auth, "TRUSTED_PROXIES", {_PROXY})
    request = make_request(ip=_PROXY, headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})
    assert auth._client_ip(request) == "198.51.100.7"


def test_client_ip_salta_varios_proxies_de_confianza_encadenados(monkeypatch):
    monkeypatch.setattr(auth, "TRUSTED_PROXIES", {_PROXY, "10.0.0.2"})
    request = make_request(ip=_PROXY, headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.7, 10.0.0.2"})
    assert auth._client_ip(request) == "198.51.100.7"


def test_client_ip_sin_xff_usa_la_ip_del_proxy(monkeypatch):
    monkeypatch.setattr(auth, "TRUSTED_PROXIES", {_PROXY})
    assert auth._client_ip(make_request(ip=_PROXY)) == _PROXY


def test_login_no_se_esquiva_cambiando_x_forwarded_for_en_cada_intento(monkeypatch):
    monkeypatch.setattr(auth, "TRUSTED_PROXIES", {_PROXY})
    monkeypatch.setattr(auth.db_admins, "obtener_hash", lambda username: None)
    req = LoginRequest(username="nadie", password="x")
    ip_real = "198.51.100.20"
    for i in range(auth.LOGIN_MAX_INTENTOS):
        request = make_request(ip=_PROXY, headers={"X-Forwarded-For": f"1.2.3.{i}, {ip_real}"})
        with pytest.raises(HTTPException) as exc:
            auth.login(req, request, Response())
        assert exc.value.status_code == 401

    request = make_request(ip=_PROXY, headers={"X-Forwarded-For": f"1.2.3.99, {ip_real}"})
    with pytest.raises(HTTPException) as exc:
        auth.login(req, request, Response())
    assert exc.value.status_code == 429


# --- limitar_lecturas_estudiante / limitar_escrituras_kiosko -------------
#
# Estructuralmente idénticos (mismo dict de ventanas deslizantes, mismo
# criterio de "por credencial, no por IP"), así que se prueban con el mismo
# helper parametrizado por la función y el máximo que le corresponde.

_LIMITADORES = [
    (auth.limitar_lecturas_estudiante, "LECTURAS_ESTUDIANTE_MAX_POR_MINUTO"),
    (auth.limitar_escrituras_kiosko, "KIOSKO_MAX_ESCRITURAS_MIN"),
]


def _maximo(nombre_attr):
    return getattr(auth, nombre_attr)


@pytest.mark.parametrize("limitador,nombre_max", _LIMITADORES)
def test_limitador_exime_al_admin_sin_tocar_los_contadores(limitador, nombre_max):
    actor = {"role": "admin", "sub": "admin"}
    maximo = _maximo(nombre_max)
    for _ in range(maximo + 5):
        assert limitador(make_request(), actor) is actor
    assert not auth._lecturas_estudiante
    assert not auth._escrituras_kiosko


@pytest.mark.parametrize("limitador,nombre_max", _LIMITADORES)
def test_limitador_bloquea_al_superar_el_maximo_por_minuto(limitador, nombre_max):
    actor = {"role": "kiosk", "sub": "PC-01", "pc_id": "PC-01"}
    maximo = _maximo(nombre_max)
    for _ in range(maximo):
        limitador(make_request(), actor)
    with pytest.raises(HTTPException) as exc:
        limitador(make_request(), actor)
    assert exc.value.status_code == 429


@pytest.mark.parametrize("limitador,nombre_max", _LIMITADORES)
def test_limitador_cuenta_por_credencial_y_no_por_ip(limitador, nombre_max):
    # Misma credencial, una IP distinta en cada llamada: si el límite fuera
    # por IP, ninguna llamada individual se acercaría al máximo. Como es por
    # credencial, las llamadas se acumulan igual y la próxima excede el límite.
    actor = {"role": "kiosk", "sub": "PC-02", "pc_id": "PC-02"}
    maximo = _maximo(nombre_max)
    for i in range(maximo):
        limitador(make_request(ip=f"203.0.113.{i % 250}"), actor)
    with pytest.raises(HTTPException):
        limitador(make_request(ip="198.51.100.77"), actor)


@pytest.mark.parametrize("limitador,nombre_max", _LIMITADORES)
def test_limitador_sin_credencial_cae_a_ip_y_no_mezcla_ips_distintas(limitador, nombre_max):
    # Si el actor no trae "sub" identificable (caso borde, no debería pasar en
    # producción con require_kiosk_or_admin), el límite cae a la IP como
    # respaldo — dos IPs distintas no comparten contador.
    actor_sin_sub = {"role": "kiosk"}
    maximo = _maximo(nombre_max)
    ip_a = "203.0.113.30"
    ip_b = "203.0.113.31"
    for _ in range(maximo):
        limitador(make_request(ip=ip_a), actor_sin_sub)
    with pytest.raises(HTTPException):
        limitador(make_request(ip=ip_a), actor_sin_sub)
    # ip_b todavía no gastó nada de su propio límite.
    limitador(make_request(ip=ip_b), actor_sin_sub)


def test_purgar_lecturas_expiradas_libera_memoria():
    auth._lecturas_estudiante["PC-viejo"] = [time.time() - 61]
    auth._purgar_lecturas_expiradas()
    assert "PC-viejo" not in auth._lecturas_estudiante


def test_purgar_escrituras_expiradas_libera_memoria():
    auth._escrituras_kiosko["PC-viejo"] = [time.time() - 61]
    auth._purgar_escrituras_expiradas()
    assert "PC-viejo" not in auth._escrituras_kiosko
