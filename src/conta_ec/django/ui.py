"""Los enganches con la interfaz del proyecto.

El paquete no trae pantallas propias hechas con la plantilla de un proyecto: los
marcos (`marco`), los campos de formulario (`controles`) y la plantilla que envuelve
las páginas los pone quien lo instala, y se cambian desde `settings.py` con
``CONTA_EC_MARCO`` y ``CONTA_EC_CAMPOS``. Así el paquete no depende de un proyecto
concreto y el proyecto puede tener su propio aspecto.
"""

from __future__ import annotations

from typing import Any

__all__ = ["campos", "marco"]

#: Dónde están, si el proyecto no dice otra cosa.
MARCO_POR_DEFECTO = "facturero.marco.marco"
CAMPOS_POR_DEFECTO = "facturero.controles"


def _traer(ruta: str) -> Any:
    from django.utils.module_loading import import_string

    return import_string(ruta)


def _ajuste(nombre: str, por_defecto: str) -> str:
    from django.conf import settings

    return getattr(settings, nombre, por_defecto)


def marco(request: Any) -> dict:
    """El contexto del marco de la aplicación (menú, usuario, avisos…)."""
    return _traer(_ajuste("CONTA_EC_MARCO", MARCO_POR_DEFECTO))(request)


def campos() -> Any:
    """El módulo con los campos de formulario del proyecto."""
    return _traer(_ajuste("CONTA_EC_CAMPOS", CAMPOS_POR_DEFECTO))
