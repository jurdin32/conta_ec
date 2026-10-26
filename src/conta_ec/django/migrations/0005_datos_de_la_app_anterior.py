"""Trae los datos de una instalación que tenía la contabilidad dentro del proyecto.

Antes el paquete no existía y las tablas se llamaban ``contabilidad_*``. Si esas
tablas están ahí, se copian sus filas a las del paquete (``conta_ec_*``) y se dejan
como estaban: así el plan de cuentas, los asientos y las compras no se pierden.
En una instalación nueva no hay nada que copiar y esto no hace nada.
"""

from __future__ import annotations

from django.db import migrations, connection

#: Cómo se llamaban las tablas antes.
PREFIJO_VIEJO = "contabilidad_"
PREFIJO_NUEVO = "conta_ec_"


def _tablas() -> set:
    return set(connection.introspection.table_names())


def traer(apps, schema_editor):
    tablas = _tablas()
    viejas = sorted(t for t in tablas if t.startswith(PREFIJO_VIEJO))

    with connection.cursor() as cursor:
        for vieja in viejas:
            nueva = PREFIJO_NUEVO + vieja[len(PREFIJO_VIEJO):]
            if nueva not in tablas:
                continue
            columnas = [
                columna.name
                for columna in connection.introspection.get_table_description(cursor, nueva)
            ]
            lista = ", ".join(f'"{nombre}"' for nombre in columnas)
            cursor.execute(
                f'INSERT OR IGNORE INTO "{nueva}" ({lista}) '
                f'SELECT {lista} FROM "{vieja}"'
            )


def devolver(apps, schema_editor):
    """Al volver atrás los datos se quedan en las tablas del paquete."""
    return


class Migration(migrations.Migration):
    dependencies = [("conta_ec", "0004_los_ajustes_de_la_contabilidad")]

    operations = [migrations.RunPython(traer, devolver)]
