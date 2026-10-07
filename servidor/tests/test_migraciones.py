"""Tests del registro de migraciones de `db/schema.py` con una conexión falsa:
comprueban que cada migración se aplica una sola vez y queda registrada, sin
abrir MySQL. El SQL de cada migración se probó contra MySQL real; acá solo
importa la lógica de qué se ejecuta y cuándo."""

from db import schema


class _Cursor:
    def __init__(self, filas):
        self._filas = filas

    def fetchone(self):
        return self._filas[0] if self._filas else None

    def fetchall(self):
        return self._filas


class _ConexionFalsa:
    def __init__(self, ya_aplicadas=()):
        self.registradas = list(ya_aplicadas)
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "GET_LOCK" in sql:
            return _Cursor([{"ok": 1}])
        if sql.startswith("SELECT version FROM schema_migraciones"):
            return _Cursor([{"version": v} for v in self.registradas])
        if sql.startswith("INSERT INTO schema_migraciones"):
            self.registradas.append(params[0])
        return _Cursor([])

    def commit(self):
        pass


def _migraciones_de_prueba(monkeypatch, llamadas):
    migraciones = [
        (1, "uno", lambda conn: llamadas.append(1)),
        (2, "dos", lambda conn: llamadas.append(2)),
    ]
    monkeypatch.setattr(schema, "MIGRACIONES", migraciones)


def test_aplica_las_pendientes_en_orden_y_las_registra(monkeypatch):
    llamadas = []
    _migraciones_de_prueba(monkeypatch, llamadas)
    conn = _ConexionFalsa()
    schema._aplicar_migraciones(conn)
    assert llamadas == [1, 2]
    assert conn.registradas == [1, 2]
    assert any("RELEASE_LOCK" in s for s in conn.sql)


def test_no_reaplica_las_ya_registradas(monkeypatch):
    llamadas = []
    _migraciones_de_prueba(monkeypatch, llamadas)
    schema._aplicar_migraciones(_ConexionFalsa(ya_aplicadas=[1]))
    assert llamadas == [2]


def test_si_una_falla_no_se_registra_y_se_libera_el_lock(monkeypatch):
    def falla(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(schema, "MIGRACIONES", [(1, "falla", falla)])
    conn = _ConexionFalsa()
    try:
        schema._aplicar_migraciones(conn)
    except RuntimeError:
        pass
    assert conn.registradas == []
    assert any("RELEASE_LOCK" in s for s in conn.sql)


def test_versiones_unicas_y_crecientes():
    versiones = [v for v, _, _ in schema.MIGRACIONES]
    assert versiones == sorted(set(versiones))
