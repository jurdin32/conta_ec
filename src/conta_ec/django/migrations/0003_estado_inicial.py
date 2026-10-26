"""Pone el estado de situación inicial en el menú de contabilidad."""

from __future__ import annotations

from django.db import migrations

OPCIONES = (
    (
        "estado_inicial",
        "Situación inicial",
        "/contabilidad/estados/situacion-inicial/",
        "report",
        8,
    ),
)


def sembrar(apps, schema_editor):
    Opcion = apps.get_model("personalize_options", "Opcion")
    for clave, nombre, url, icono, orden in OPCIONES:
        Opcion.objects.update_or_create(
            clave=clave,
            defaults={
                "nombre": nombre,
                "grupo": "Contabilidad",
                "orden": orden,
                "url": url,
                "icono": icono,
                "en_menu": True,
                "activo": True,
            },
        )


def deshacer(apps, schema_editor):
    Opcion = apps.get_model("personalize_options", "Opcion")
    Opcion.objects.filter(clave__in=[fila[0] for fila in OPCIONES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("conta_ec", "0002_plan_y_opciones"),
        ("personalize_options", "0003_sembrar_opciones"),
    ]

    operations = [migrations.RunPython(sembrar, deshacer)]
