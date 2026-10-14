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
- **Resumen del día**: total de sesiones, estudiantes distintos, PCs usadas, duración promedio por sesión y **PCs activas** (las que se comunicaron con el servidor en los últimos 5 minutos, estén en uso o no).
- **Exportar a CSV**: botón para descargar como hoja de cálculo exactamente lo que muestra la tabla, con los filtros aplicados.
- La información se actualiza sola cada 30 segundos; no hace falta recargar la página.

## Pestaña PCs

Muestra el estado de cada PC de la sala.

- **Tarjetas de estado en vivo**: cada PC aparece como **En uso** (con carnet, nombre y hora de inicio de quien la usa, o "Invitado"), **Disponible** (encendida y libre) o **No disponible** (no se comunica con el servidor desde hace más de 2 minutos: apagada o sin red).
- **Tabla de mantenimiento**: uso en sesiones y horas encendida desde el último mantenimiento, specs resumidas (CPU, RAM, almacenamiento, temperatura, alerta de disco) y estado de salud según las horas encendida:
  - 🟢 **Óptimo** — menos de 300 horas desde el último mantenimiento.
  - 🟡 **Pendiente** — entre 300 y 400 horas, conviene programar mantenimiento pronto.
  - 🔴 **Crítico** — más de 400 horas, requiere mantenimiento.
- **Registrar mantenimiento**: botón por cada PC para marcar que se le hizo mantenimiento hoy — esto reinicia su contador de horas.
- **API key de cada PC**: cada PC necesita su propia clave para comunicarse con el servidor. La columna "API key" indica si está configurada.
  - **Generar API key** (o **Rotar**, si ya tenía): crea una clave nueva y la muestra **una sola vez** — copiala y pegala en el asistente de configuración de esa PC. Si la PC ya tenía una clave, la anterior deja de funcionar al instante.
  - **Revocar API key**: desactiva la clave de esa PC (por ejemplo, si se la robaron); la PC deja de sincronizar hasta que se le genere una nueva.
  - **Nueva PC**: para una PC que todavía no aparece en la tabla, escribí el `PC_ID` que muestra su asistente de configuración y presioná **Generar API key**.

## Pestaña Estudiantes

- **Tabla de estudiantes** registrados en el sistema, con buscador local (por nombre, carnet, carrera, etc.).
- **Alta/edición**: botón para registrar un estudiante nuevo o editar los datos de uno existente (nombre, año de nacimiento, facultad, carrera, sexo) mediante un formulario emergente. El carnet lleva dos letras y cinco números (por ejemplo `MV23036`). La facultad y la carrera deben ser una combinación válida del catálogo de la universidad: al escribir la facultad, el formulario sugiere sus carreras.
- **Eliminar**: botón **Eliminar** en cada fila. Solo se puede borrar un estudiante que **no tenga sesiones registradas** — si las tiene, el sistema lo impide para no perder el historial de uso.

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
2. Ingresá tu contraseña actual y la nueva (entre 12 y 128 caracteres, distinta de tu nombre de usuario y de las contraseñas de ejemplo publicadas en el proyecto).
3. Confirmá. Tu sesión actual sigue abierta; cualquier otra sesión abierta con la contraseña anterior (en otra PC o navegador) se cierra sola. La próxima vez que inicies sesión, usá la contraseña nueva.

Si te equivocás en la contraseña actual, el sistema te avisa y no hace el cambio.

## Cerrar sesión

Botón **Cerrar sesión** arriba a la derecha. Se recomienda cerrar sesión si vas a dejar la PC desatendida, especialmente en equipos compartidos.

## Preguntas frecuentes

**No me deja entrar, dice que la IP está bloqueada.**
Superaste el número de intentos fallidos permitidos. Esperá el tiempo indicado (configurado por quien instaló el sistema, normalmente 15 minutos) y volvé a intentar con la contraseña correcta.

**Una PC no aparece como activa (o aparece "No disponible") aunque está encendida.**
La PC envía una señal al servidor cada 30 segundos mientras el programa del kiosko está abierto. Se cuenta como activa si hubo señal en los últimos 5 minutos, y figura "No disponible" si no la hubo en los últimos 2. Si la API key de esa PC fue revocada o no está configurada, el servidor rechaza sus señales. Si acaba de encenderse o perdió la red, puede tardar un momento en aparecer. Si el problema persiste, revisá la conexión de red de esa PC o contactá a soporte técnico.

**Aparece una sesión de "invitado" sin nombre.**
Es normal: corresponde a alguien que usó la PC sin ser estudiante (personal administrativo, docente o visitante), que no completa datos personales al iniciar sesión en el kiosko.

**Quiero borrar un estudiante pero el sistema no me deja.**
El estudiante tiene sesiones de uso registradas — el sistema protege el historial. Si de verdad necesitás eliminarlo, contactá a soporte técnico.

**¿Los datos se pierden si se corta la luz o el internet?**
No. Cada PC guarda las sesiones localmente y las envía al servidor apenas recupera conexión. El panel puede tardar unos segundos o minutos en reflejar sesiones de PCs que estuvieron desconectadas.
