"""Etiquetas propias de la contabilidad."""

from __future__ import annotations

from django import template

register = template.Library()

__all__ = ["campo"]


@register.filter(name="campo")
def campo(formulario, nombre: str):
    """Un campo del formulario por su nombre, para pintarlos en el orden deseado."""
    return formulario[nombre]
