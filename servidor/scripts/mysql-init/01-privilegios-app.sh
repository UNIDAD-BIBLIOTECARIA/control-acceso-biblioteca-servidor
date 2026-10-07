# shellcheck shell=bash
# Lo carga la imagen oficial de MySQL una sola vez, al inicializar un volumen
# de datos vacío (montado en /docker-entrypoint-initdb.d por los compose).
#
# La imagen le da al usuario de la app (MYSQL_USER) ALL PRIVILEGES sobre la
# base. Acá se reduce a lo que el servidor usa: CRUD de datos más el DDL que
# hacen init_db y las migraciones (CREATE TABLE, ALTER, índices y claves
# foráneas). Queda fuera, entre otros, DROP de tablas, GRANT OPTION, LOCK
# TABLES, triggers, rutinas, eventos y vistas: una inyección SQL futura no
# podría borrar tablas enteras ni dejar código persistente en la base.
#
# restore_db.sh restaura con root, porque el volcado incluye DROP TABLE y
# LOCK TABLES.
#
# Este archivo NO debe tener permiso de ejecución: la imagen hace `source` de
# los .sh sin ese bit (y así están disponibles `docker_process_sql` y el
# `set -e` del entrypoint, que aborta la inicialización si algo falla); a los
# ejecutables los corre como proceso aparte, donde esa función no existe.

docker_process_sql --database=mysql <<EOSQL
REVOKE ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* FROM '${MYSQL_USER}'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
    ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
EOSQL
