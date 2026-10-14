"""Tests de las consultas de reportes/mantenimiento y del heartbeat de /estado.
La conexión a MySQL se reemplaza por un doble que guarda el SQL y los
parámetros ejecutados: se verifica qué se le pide a la base, no el resultado."""

import contextlib

from db import estado as db_estado
from db import pcs as db_pcs
from db import reportes as db_reportes
from models import EstadoPayload


class _Resultado:
    def fetchall(self):
        return []

    def fetchone(self):
        return {}


class _ConexionFalsa:
    def __init__(self):
        self.ejecutado = []

    def execute(self, sql, params=None):
        self.ejecutado.append((sql, params))
        return _Resultado()

    def commit(self):
        pass


def _usar_conexion_falsa(monkeypatch, modulo):
    conn = _ConexionFalsa()
    monkeypatch.setattr(modulo, "conexion", lambda: contextlib.nullcontext(conn))
    return conn


def test_filtro_por_carrera_se_aplica_tambien_a_las_sesiones_en_curso(monkeypatch):
    conn = _usar_conexion_falsa(monkeypatch, db_reportes)

    db_reportes.listar_sesiones(fecha="2026-01-01", carrera="Arquitectura")

    sql, params = conn.ejecutado[0]
    assert "e.carrera = %s" in sql
    assert "e2.carrera = %s" in sql
    assert params.count("Arquitectura") == 2


def test_sesion_en_curso_ya_sincronizada_no_se_lista_dos_veces(monkeypatch):
    conn = _usar_conexion_falsa(monkeypatch, db_reportes)

    db_reportes.listar_sesiones(fecha="2026-01-01")

    sql, _ = conn.ejecutado[0]
    parte_en_vivo = sql.split("UNION ALL")[1]
    assert "NOT EXISTS (SELECT 1 FROM sesiones sx WHERE sx.pc_id = ep.pc_id AND sx.hora_inicio = ep.hora_inicio)" in parte_en_vivo


def test_uso_desde_mantenimiento_no_cuenta_dos_veces_la_sesion_en_curso(monkeypatch):
    conn = _usar_conexion_falsa(monkeypatch, db_pcs)

    db_pcs.listar_mantenimiento()

    sql, _ = conn.ejecutado[0]
    parte_en_vivo = sql.split("UNION ALL")[1]
    assert "NOT EXISTS" in parte_en_vivo
    assert "sx.hora_inicio = estado_pcs.hora_inicio" in parte_en_vivo


def test_heartbeat_de_estado_actualiza_la_ultima_conexion_de_la_pc(monkeypatch):
    conn = _usar_conexion_falsa(monkeypatch, db_estado)
    llamadas = []
    monkeypatch.setattr(db_estado.db_pcs, "upsert_conexion", lambda *a: llamadas.append(a))

    db_estado.actualizar_estado(EstadoPayload(pc_id="PC-01", sesion_activa=False), "192.168.1.20")

    assert len(llamadas) == 1
    _, pc_id, nombre, ultima_conexion, ip = llamadas[0]
    assert (pc_id, nombre, ip) == ("PC-01", None, "192.168.1.20")
    assert ultima_conexion
    assert any("INTO estado_pcs" in sql for sql, _ in conn.ejecutado)


def test_upsert_conexion_no_borra_nombre_ni_ip_si_no_vienen():
    conn = _ConexionFalsa()

    db_pcs.upsert_conexion(conn, "PC-01", None, "2026-01-01T10:00:00", None)

    sql, _ = conn.ejecutado[0]
    assert "nombre = COALESCE(VALUES(nombre), nombre)" in sql
    assert "ip_reportada = COALESCE(VALUES(ip_reportada), ip_reportada)" in sql
