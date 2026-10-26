"""Configuración de la aplicación Django de la contabilidad."""

from __future__ import annotations

from django.apps import AppConfig

__all__ = ["ContaEcConfig"]


class ContaEcConfig(AppConfig):
    """App de Django con la contabilidad del negocio.

    Se registra en ``INSTALLED_APPS`` como::

        INSTALLED_APPS = [
            ...,
            "conta_ec.django",
        ]

    El ``label`` es ``conta_ec`` para que las tablas queden como
    ``conta_ec_asiento`` y ``conta_ec_cuenta``.
    """

    name = "conta_ec.django"
    label = "conta_ec"
    verbose_name = "Contabilidad"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Declara los ajustes, siembra al migrar y escucha al SRI.

        Las pantallas del paquete piden permiso con ``personalize_options`` y el
        admin se registra solo (el módulo ``admin`` del paquete se descubre con la
        app). Los ajustes viven en la tabla del paquete y se siembran al migrar,
        sin que el proyecto tenga que poner nada.
        """
        from django.db.models.signals import post_migrate

        from . import ajustes

        ajustes.declarar()
        post_migrate.connect(
            ajustes.sembrar_al_migrar,
            sender=self,
            dispatch_uid="conta_ec_sembrar_ajustes",
        )

        # La contabilización automática escucha lo que el SRI autoriza.
        if self._el_sri_esta_puesto():
            from . import signals  # noqa: F401

    @staticmethod
    def _el_sri_esta_puesto() -> bool:
        """¿Está puesto el paquete de los comprobantes? (`is_installed` mira el
        nombre de la app, no su etiqueta: la etiqueta del paquete es ``sri_fe``.)"""
        from django.apps import apps

        return apps.is_installed("factec.django")
