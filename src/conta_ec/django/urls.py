"""Direcciones de la contabilidad."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "contabilidad"

urlpatterns = [
    path("", views.tablero, name="tablero"),
    path("contabilizar-pendientes/", views.contabilizar_pendientes, name="contabilizar_pendientes"),

    # Plan de cuentas
    path("plan/", views.plan, name="plan"),
    path("plan/nueva/", views.cuenta, name="cuenta_nueva"),
    path("plan/<int:pk>/", views.cuenta, name="cuenta"),

    # Asientos
    path("asientos/", views.asientos, name="asientos"),
    path("asientos/nuevo/", views.asiento, name="asiento_nuevo"),
    path("asientos/<int:pk>/", views.asiento, name="asiento"),
    path("asientos/<int:pk>/ver/", views.asiento_detalle, name="asiento_detalle"),
    path("asientos/<int:pk>/accion/<str:que>/", views.asiento_accion, name="asiento_accion"),

    # Libros y estados
    path("libro-diario/", views.libro_diario, name="libro_diario"),
    path("libro-mayor/", views.libro_mayor, name="libro_mayor"),
    path("balance/", views.balance, name="balance"),
    path("estados/", views.estados, name="estados"),
    path("estados/resultados/", views.estado_resultados, name="estado_resultados"),
    path("estados/situacion/", views.estado_situacion, name="estado_situacion"),
    path(
        "estados/situacion-inicial/",
        views.estado_situacion_inicial,
        name="estado_situacion_inicial",
    ),
    path("estados/flujos/", views.estado_flujos, name="estado_flujos"),
    path("estados/patrimonio/", views.estado_patrimonio, name="estado_patrimonio"),

    # Cierre y compras
    path("cierre/", views.cierre, name="cierre"),
    path("compras/", views.compras, name="compras"),
    path("compras/nueva/", views.compra, name="compra_nueva"),
    path("compras/<int:pk>/", views.compra, name="compra"),

    # Configuración y anexos
    path("configuracion/", views.configuracion, name="configuracion"),
    path("anexos/", views.anexos_sri, name="anexos"),
    path("anexos/descargar/<str:que>/", views.descargar, name="descargar"),
    path("iva/", views.iva, name="iva"),
    path("retenciones/", views.retenciones, name="retenciones"),

    # RDEP
    path("empleados/", views.empleados, name="empleados"),
    path("empleados/nuevo/", views.empleado, name="empleado_nuevo"),
    path("empleados/<int:pk>/", views.empleado, name="empleado"),
]
