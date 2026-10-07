FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# El contenedor de producción corre con el sistema de archivos de solo lectura
# (docker-compose.prod.yml): que Python no intente escribir .pyc.
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

# H7: uvicorn no debe correr como root dentro del contenedor — limita el
# impacto de un eventual RCE al privilegio de un usuario sin permisos.
RUN useradd --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Detecta un uvicorn colgado que no crashea pero tampoco responde — ver
# healthcheck.py. `restart: unless-stopped` en los docker-compose*.yml no
# alcanza para ese caso por sí solo, pero sí reacciona una vez que Docker
# marca el contenedor "unhealthy".
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python healthcheck.py

ENTRYPOINT ["./docker-entrypoint.sh"]
