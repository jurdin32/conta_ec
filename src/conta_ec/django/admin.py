"""El admin de la contabilidad: para revisar, no para el día a día."""

from __future__ import annotations

from django.contrib import admin
from typing import Any

from .models import (
    AjusteDeLaContabilidad,
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    Empleado,
    EstadoAsiento,
    LineaAsiento,
    PeriodoContable,
)


def _cerrado(objeto: Any) -> bool:
    """¿La partida ya está en los libros? Entonces no se edita, se anula."""
    return (
        objeto is not None
        and getattr(objeto, "estado", "") != EstadoAsiento.BORRADOR.value
    )


def _todos_los_campos(modelo: Any) -> list[str]:
    return [campo.name for campo in modelo._meta.fields]


class LineaInline(admin.TabularInline):
    model = LineaAsiento
    extra = 0
    autocomplete_fields = ["cuenta", "tercero"]

    def get_readonly_fields(self, request, obj=None):
        if _cerrado(obj):
            return _todos_los_campos(self.model)
        return super().get_readonly_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        if _cerrado(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if _cerrado(obj):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "tipo", "naturaleza", "nivel", "permite_movimientos", "activa"]
    list_filter = ["tipo", "naturaleza", "activa", "permite_movimientos"]
    search_fields = ["codigo", "nombre"]
    ordering = ["codigo"]


@admin.register(PeriodoContable)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "ejercicio", "mes", "fecha_inicio", "fecha_fin", "estado"]
    list_filter = ["estado", "ejercicio"]
    search_fields = ["nombre"]


@admin.register(Asiento)
class AsientoAdmin(admin.ModelAdmin):
    list_display = ["numero", "fecha", "concepto", "tipo", "estado", "periodo"]
    list_filter = ["estado", "tipo", "periodo__ejercicio"]
    search_fields = ["numero", "concepto", "referencia"]
    date_hierarchy = "fecha"
    inlines = [LineaInline]
    autocomplete_fields = ["comprobante"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("periodo")

    # Una partida contabilizada es un documento: no se edita ni se borra desde el
    # admin. Si hay que corregirla, se anula y se hace otra, y así queda el rastro.
    def get_readonly_fields(self, request, obj=None):
        if _cerrado(obj):
            return _todos_los_campos(self.model)
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        if _cerrado(obj):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(LineaAsiento)
class LineaAdmin(admin.ModelAdmin):
    list_display = ["asiento", "cuenta", "descripcion", "debe", "haber"]
    list_filter = ["cuenta__tipo"]
    search_fields = ["descripcion", "documento"]
    autocomplete_fields = ["asiento", "cuenta", "tercero"]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and _cerrado(obj.asiento):
            return _todos_los_campos(self.model)
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and _cerrado(obj.asiento):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ["fecha", "proveedor", "tipo_comprobante", "numero", "total", "asiento"]
    list_filter = ["tipo_comprobante", "fecha"]
    search_fields = ["numero", "proveedor__razon_social", "concepto"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["proveedor", "cuenta", "retencion", "asiento"]


@admin.register(ConfiguracionContable)
class ConfiguracionAdmin(admin.ModelAdmin):
    list_display = ["nombre", "activa", "tipo_empleador", "ente_seg_social"]
    list_filter = ["activa"]


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ["anio", "apellidos", "nombres", "identificacion", "suel_sal", "val_ret", "activo"]
    list_filter = ["anio", "activo", "tipo_identificacion"]
    search_fields = ["apellidos", "nombres", "identificacion"]


@admin.register(AjusteDeLaContabilidad)
class AjusteDeLaContabilidadAdmin(admin.ModelAdmin):
    """Los ajustes de la contabilidad: lo único que se escribe es el valor.

    La clave es la que lee el paquete y no se toca; el tipo, el grupo y para qué
    sirve vienen de la declaración y se refrescan al migrar.
    """

    list_display = ("clave", "grupo", "valor", "tipo", "actualizado")
    list_filter = ("grupo", "tipo")
    search_fields = ("clave", "valor", "descripcion")
    ordering = ("grupo", "orden", "clave")
    readonly_fields = (
        "clave",
        "tipo",
        "grupo",
        "descripcion",
        "orden",
        "editable",
        "actualizado",
    )
    fields = ("clave", "grupo", "tipo", "descripcion", "valor", "orden", "editable", "actualizado")
    save_on_top = True
    list_per_page = 50

    def has_add_permission(self, request: Any) -> bool:
        # Los declara el paquete; se cambian, no se inventan.
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        # Y tampoco se borran: volverían a aparecer al migrar.
        return False
