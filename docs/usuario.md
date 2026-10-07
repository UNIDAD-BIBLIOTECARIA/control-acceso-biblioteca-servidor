# Guía de usuario — Panel Administrativo de Biblioteca

Esta guía es para el personal administrativo que usa el **panel web** para controlar el acceso a las PCs de la biblioteca, ver quién las está usando y generar reportes. No requiere conocimientos técnicos.

Si sos desarrollador y buscás cómo instalar o modificar el sistema, ver [`desarrollo/despliegue.md`](./desarrollo/despliegue.md) y [`desarrollo/estructura.md`](./desarrollo/estructura.md).

## Acceso al panel

Abrí en el navegador la dirección del servidor (por ejemplo `http://IP-DE-LA-PC-MAESTRA:8000`, o la URL del túnel si el sistema fue configurado con acceso externo). Vas a ver una pantalla de login:

1. Ingresá tu **usuario** y **contraseña** de administrador.
2. Presioná **Ingresar**.

Si la contraseña es incorrecta, el sistema muestra un mensaje de error. Después de varios intentos fallidos, el acceso queda bloqueado temporalmente por seguridad (unos minutos) — esperá y volvé a intentar.

> La primera vez que entrás con la contraseña inicial que te dio quien instaló el sistema, **cambiala de inmediato** (ver sección "Cambiar tu contraseña" más abajo). Solo vos vas a conocer la contraseña definitiva.

Una vez adentro, vas a ver cuatro pestañas: **Sesiones**, **PCs**, **Estudiantes** y **Estadísticas**.

## Pestaña Sesiones

Muestra el uso de las PCs del día actual.

- **Tabla de sesiones**: quién usó cada PC, a qué hora entró y salió, y cuánto tiempo estuvo. Las sesiones que todavía están en curso muestran el tiempo transcurrido actualizándose cada minuto.
- Las sesiones de **invitado** (personal sin carnet: administrativo, docente, visitante) aparecen marcadas con una etiqueta amarilla, sin nombre de estudiante.
- **Filtros** disponibles arriba de la tabla: fecha, carrera, facultad, PC, o carnet/nombre. Se pueden combinar.
- **Resumen del día**: totales de sesiones, estudiantes distintos y PCs usadas.
- **Badge de PCs activas**: indica cuántas PCs tienen conexión reciente con el servidor (últimos 5 minutos).
- **Exportar a CSV**: botón para descargar la tabla filtrada como archivo de hoja de cálculo.
- La información se actualiza sola cada 30 segundos; no hace falta recargar la página.

## Pestaña PCs

Muestra el estado de cada PC de la sala.

- **Tarjetas de estado en vivo**: cada PC aparece como "libre" o "en uso" (con el nombre de quien la está usando, si corresponde).
- **Tabla de mantenimiento**: specs resumidas de cada máquina (CPU, RAM, almacenamiento) y su estado de salud:
  - 🟢 **Óptimo** — menos de 300 horas de uso desde el último mantenimiento.
  - 🟡 **Pendiente** — entre 300 y 400 horas, conviene programar mantenimiento pronto.
  - 🔴 **Crítico** — más de 400 horas, requiere mantenimiento.
- **Registrar mantenimiento**: botón por cada PC para marcar que se le hizo mantenimiento hoy — esto reinicia su contador de horas.

## Pestaña Estudiantes

- **Tabla de estudiantes** registrados en el sistema, con buscador local (por nombre, carnet, carrera, etc.).
- **Alta/edición**: botón para registrar un estudiante nuevo o editar los datos de uno existente (nombre, año de nacimiento, carrera, facultad, sexo) mediante un formulario emergente.
- **Eliminar**: solo se puede borrar un estudiante que **no tenga sesiones registradas** — si las tiene, el sistema lo impide para no perder el historial de uso.

## Pestaña Estadísticas

Gráficos para análisis de uso a lo largo del tiempo.

- **Rangos rápidos**: últimos 7, 30, 90 o 365 días, o un rango de fechas manual.
- **Gráficos disponibles**:
  - Sesiones por día (tendencia).
  - Distribución de uso por hora del día.
  - Distribución por sexo (gráfico de dona).
  - Top carreras, facultades y PCs más usadas (barras horizontales).

## Cambiar tu contraseña

1. Con sesión iniciada, presioná **Cambiar contraseña** (arriba, junto a "Cerrar sesión").
2. Ingresá tu contraseña actual y la nueva (entre 12 y 128 caracteres, distinta de tu nombre de usuario).
3. Confirmá. La próxima vez que inicies sesión, usá la contraseña nueva.

Si te equivocás en la contraseña actual, el sistema te avisa y no hace el cambio.

## Cerrar sesión

Botón **Cerrar sesión** arriba a la derecha. Se recomienda cerrar sesión si vas a dejar la PC desatendida, especialmente en equipos compartidos.

## Preguntas frecuentes

**No me deja entrar, dice que la IP está bloqueada.**
Superaste el número de intentos fallidos permitidos. Esperá el tiempo indicado (configurado por quien instaló el sistema, normalmente 15 minutos) y volvé a intentar con la contraseña correcta.

**Una PC no aparece como activa aunque está encendida.**
El sistema marca una PC como activa si reportó conexión en los últimos 5 minutos. Si acaba de encenderse o perdió la red, puede tardar un momento en aparecer. Si el problema persiste, revisá la conexión de red de esa PC o contactá a soporte técnico.

**Aparece una sesión de "invitado" sin nombre.**
Es normal: corresponde a alguien que usó la PC sin ser estudiante (personal administrativo, docente o visitante), que no completa datos personales al iniciar sesión en el kiosko.

**Quiero borrar un estudiante pero el sistema no me deja.**
El estudiante tiene sesiones de uso registradas — el sistema protege el historial. Si de verdad necesitás eliminarlo, contactá a soporte técnico.

**¿Los datos se pierden si se corta la luz o el internet?**
No. Cada PC guarda las sesiones localmente y las envía al servidor apenas recupera conexión. El panel puede tardar unos segundos o minutos en reflejar sesiones de PCs que estuvieron desconectadas.
