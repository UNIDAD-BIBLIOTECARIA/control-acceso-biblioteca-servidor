"""`seudonimo` reemplaza al carnet en los logs del servidor: tiene que ser
estable (para seguir a un estudiante en el log) y no dejar ver el carnet."""

from seudonimo import seudonimo


def test_es_estable_y_no_contiene_el_carnet():
    assert seudonimo("AB12345") == seudonimo("AB12345")
    assert "AB12345" not in seudonimo("AB12345")
    assert seudonimo("AB12345") != seudonimo("AB12346")


def test_depende_de_secret_key(monkeypatch):
    antes = seudonimo("AB12345")
    monkeypatch.setenv("SECRET_KEY", "otra-clave-distinta")
    assert seudonimo("AB12345") != antes


def test_sin_carnet():
    assert seudonimo(None) == "invitado"
