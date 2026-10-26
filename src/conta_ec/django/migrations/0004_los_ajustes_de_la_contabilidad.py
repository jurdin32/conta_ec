"""Los ajustes de la contabilidad, en la tabla del paquete.

Si la instalación venía de antes —con los ajustes en la tabla del proyecto, puesta
por ``personalize_options``—, se traen su valor y se borran de allí. Si no, no se
hace nada: la señal ``post_migrate`` los siembra con su valor de serie.
"""

from __future__ import annotations

from django.db import migrations, connection
from django.db.utils import OperationalError, ProgrammingError

CLAVES = ("contabilidad_contabilizar_al_autorizar", "contabilidad_periodo_automatico")


def traer(apps, schema_editor):
    Ajuste = apps.get_model("conta_ec", "AjusteDeLaContabilidad")

    tablas = set(connection.introspection.table_names())
    if "personalize_options_ajuste" not in tablas:
        return

    try:
        from django.apps import apps as global_apps

        Viejo = global_apps.get_model("personalize_options", "Ajuste")
        anteriores = {fila.clave: fila for fila in Viejo.objects.filter(clave__in=CLAVES)}
    except (LookupError, OperationalError, ProgrammingError):  # pragma: no cover
        return

    for clave, fila in anteriores.items():
        nuevo, _ = Ajuste.objects.get_or_create(
            clave=clave,
            defaults={
                "valor": fila.valor,
                "tipo": fila.tipo,
                "grupo": "Contabilidad",
                "orden": fila.orden,
                "editable": fila.editable,
                "descripcion": fila.descripcion,
            },
        )
        if not nuevo.valor:
            nuevo.valor = fila.valor
            nuevo.save(update_fields=["valor"])

    Viejo.objects.filter(clave__in=CLAVES).delete()


def devolver(apps, schema_editor):
    """Al volver atrás los ajustes se quedan donde estaban."""
    return


class Migration(migrations.Migration):
    dependencies = [("conta_ec", "0003_estado_inicial")]

    operations = [migrations.RunPython(traer, devolver)]
