"""Siembra el plan de cuentas y las opciones del menú de contabilidad."""

from __future__ import annotations

from django.db import migrations

#: (clave, nombre, url, icono, orden)
OPCIONES = (
    ("contabilidad", "Resumen contable", "/contabilidad/", "calculator", 1),
    ("plan_cuentas", "Plan de cuentas", "/contabilidad/plan/", "list", 2),
    ("asientos", "Asientos contables", "/contabilidad/asientos/", "books", 3),
    ("libro_diario", "Libro diario", "/contabilidad/libro-diario/", "receipt", 4),
    ("libro_mayor", "Libro mayor", "/contabilidad/libro-mayor/", "library", 5),
    ("balance_comprobacion", "Balance de comprobación", "/contabilidad/balance/", "table", 6),
    ("estados_financieros", "Estados financieros", "/contabilidad/estados/", "report", 7),
    ("cierre_contable", "Cierre contable", "/contabilidad/cierre/", "calendar", 8),
    ("compras", "Compras", "/contabilidad/compras/", "cart-product", 9),
    ("anexos_sri", "Anexos del SRI", "/contabilidad/anexos/", "download", 10),
    ("empleados", "Empleados (RDEP)", "/contabilidad/empleados/", "person", 11),
    ("configuracion_contable", "Configuración contable", "/contabilidad/configuracion/", "cog", 12),
)


def sembrar(apps, schema_editor):
    from conta_ec.django import plan

    Cuenta = apps.get_model("conta_ec", "Cuenta")
    ConfiguracionContable = apps.get_model("conta_ec", "ConfiguracionContable")
    plan.sembrar(Cuenta=Cuenta, ConfiguracionContable=ConfiguracionContable)

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
        ("conta_ec", "0001_initial"),
        ("personalize_options", "0003_sembrar_opciones"),
    ]

    operations = [migrations.RunPython(sembrar, deshacer)]
