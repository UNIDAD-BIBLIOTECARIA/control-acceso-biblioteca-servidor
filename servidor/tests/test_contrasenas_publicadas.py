"""Tests de `contrasenas_publicadas.py`: las contraseñas que quedaron en el
historial del repo público no deben poder usarse como contraseña de admin,
ni directamente ni como hash sembrado desde ADMIN_PASS_HASH."""

from contrasenas_publicadas import es_contrasena_publicada, es_hash_de_contrasena_publicada
from routers import auth


def test_detecta_las_contrasenas_del_historial():
    assert es_contrasena_publicada("biblioteca2026")
    assert es_contrasena_publicada("biblioteca2026$")
    assert not es_contrasena_publicada("una-contraseña-nueva-y-privada")


def test_detecta_hash_de_contrasena_publicada():
    assert es_hash_de_contrasena_publicada(auth.generar_hash("biblioteca2026"))


def test_no_marca_hash_de_contrasena_privada():
    assert not es_hash_de_contrasena_publicada(auth.generar_hash("una-contraseña-nueva-y-privada"))


def test_hash_malformado_no_se_marca():
    assert not es_hash_de_contrasena_publicada("esto-no-es-un-hash-valido")
    assert not es_hash_de_contrasena_publicada(None)
