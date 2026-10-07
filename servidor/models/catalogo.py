"""Catálogo de facultades (departamentos o extensiones) y sus carreras.

Es el mismo que ofrece el formulario de registro del kiosko (`ui/registro.py`
en el repo del cliente, donde la facultad de una extensión se guarda como
"Extensión <sede>"). Validarlo solo en el kiosko no alcanzaba: con la API key de
una PC se podían mandar valores arbitrarios que terminaban en las estadísticas
del panel. **Si se agrega o renombra una carrera, hay que actualizar los dos
repos a la vez** (primero el servidor, para que acepte el valor nuevo antes de
que algún kiosko lo envíe)."""

FACULTADES: dict[str, tuple[str, ...]] = {
    "Departamento de Ingeniería y Arquitectura": (
        "Arquitectura",
        "Ingeniería Civil",
        "Ingeniería Industrial",
        "Ingeniería Mecánica",
        "Ingeniería Eléctrica",
        "Ingeniería en Sistemas Informáticos",
    ),
    "Departamento de Ciencias Económicas": (
        "Licenciatura en Administración de Empresas",
        "Licenciatura en Contaduría Pública",
        "Licenciatura en Economía",
        "Licenciatura en Mercadeo Internacional",
        "Licenciatura en Logística Comercial Internacional (Modalidad a Distancia)",
    ),
    "Departamento de Ciencias y Humanidades": (
        "Licenciatura en Psicología",
        "Licenciatura en Sociología",
        "Licenciatura en Letras",
        "Licenciatura en Trabajo Social",
        "Licenciatura en Lenguas Modernas Especialidad Francés e Inglés",
        "Licenciatura en Ciencias de la Educación",
        "Licenciatura en Educación Inicial y Parvularia",
        "Profesorado en Educación Inicial y Parvularia",
        "Profesorado en Educación Básica",
        "Profesorado en Ciencias Sociales",
        "Profesorado en Idioma Inglés",
    ),
    "Departamento de Ciencias Naturales y Matemática": (
        "Licenciatura en Biología",
        "Licenciatura en Ciencias Químicas",
        "Licenciatura en Física",
        "Licenciatura en Matemática",
        "Profesorado en Biología",
        "Profesorado en Física",
        "Profesorado en Matemática",
        "Profesorado en Química",
    ),
    "Departamento de Medicina": (
        "Doctorado en Medicina",
        "Licenciatura en Laboratorio Clínico",
        "Licenciatura en Fisioterapia y Terapia Ocupacional",
        "Licenciatura en Anestesiología e Inhaloterapia",
    ),
    "Departamento de Química y Farmacia": (
        "Licenciatura en Química y Farmacia",
    ),
    "Departamento de Ciencias Agronómicas": (
        "Ingeniería Agronómica",
    ),
    "Departamento de Jurisprudencia y Ciencias Sociales": (
        "Licenciatura en Ciencias Jurídicas",
    ),
    "Extensión San Francisco Gotera (Morazán)": (
        "Técnico en Veterinaria y Zootecnia",
        "Técnico en Agricultura Sostenible",
        "Técnico en Turismo Ecológico y Cultural",
        "Técnico en Gestión del Desarrollo Territorial",
    ),
    "Extensión La Unión": (
        "Técnico en Veterinaria y Zootecnia",
    ),
}


def es_combinacion_valida(carrera, facultad) -> bool:
    """Una ficha puede no tener carrera ni facultad (accesos sin registro, datos
    históricos), pero si trae alguna, tienen que ser una combinación del catálogo."""
    if not carrera and not facultad:
        return True
    return carrera in FACULTADES.get(facultad, ())
