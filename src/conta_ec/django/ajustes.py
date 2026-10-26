"""Los ajustes de la contabilidad, en la tabla del propio paquete.

Lo que antes se declaraba en el proyecto como ajustes de la aplicación:

* ``contabilidad_contabilizar_al_autorizar`` — al autorizarse un comprobante del
  SRI, armar su asiento;
* ``contabilidad_periodo_automatico`` — abrir solo el período del mes de cada
  asiento.

Ahora son filas de ``conta_ec_ajustedelacontabilidad``: el paquete se lleva su
tabla, así que funciona igual con o sin el paquete de permisos puesto. Este módulo
los declara, la señal ``post_migrate`` los siembra y el servicio los lee.

De la declaración viene todo menos el valor: la clave, el tipo, el grupo y la
descripción se refrescan al migrar y no se escriben a mano.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Sequence, Tuple

__all__ = [
    "AjusteDeSerie",
    "DE_SERIE",
    "booleano",
    "declarados",
    "de_la_base",
    "poner",
    "sembrar",
    "sembrar_al_migrar",
]

#: Verdadero tal como se escribe en la base.
_SI = ("1", "si", "sí", "true", "verdadero", "on", "yes")


@dataclass(frozen=True)
class AjusteDeSerie:
    """Un ajuste que declara el paquete: su valor de serie y para qué sirve."""

    clave: str
    valor: str
    tipo: str = "texto"
    grupo: str = "Contabilidad"
    descripcion: str = ""
    orden: int = 0
    editable: bool = True


#: Los ajustes de la contabilidad.
DE_SERIE: Tuple[AjusteDeSerie, ...] = (
    AjusteDeSerie(
        "contabilidad_contabilizar_al_autorizar",
        "si",
        tipo="booleano",
        orden=1,
        descripcion=(
            "Al autorizarse un comprobante del SRI, armar su asiento con las "
            "cuentas de la configuración contable."
        ),
    ),
    AjusteDeSerie(
        "contabilidad_periodo_automatico",
        "si",
        tipo="booleano",
        orden=2,
        descripcion=(
            "Abrir solo el período del mes de cada asiento. Con «no», los períodos "
            "se abren a mano."
        ),
    ),
)

#: Lo declarado (``declarar()`` puede añadir más).
_REGISTRO: Dict[str, AjusteDeSerie] = {ajuste.clave: ajuste for ajuste in DE_SERIE}


# ------------------------------------------------------------------ declarar


def declarar(*nuevos: AjusteDeSerie) -> None:
    """Declara ajustes de la contabilidad (los de serie ya lo están)."""
    for ajuste in nuevos:
        _REGISTRO[ajuste.clave] = ajuste
    _leidos_de_la_base.cache_clear()


def declarados() -> Sequence[AjusteDeSerie]:
    """Los ajustes declarados, en el orden en que se enseñan."""
    return tuple(
        sorted(_REGISTRO.values(), key=lambda ajuste: (ajuste.grupo, ajuste.orden, ajuste.clave))
    )


# ---------------------------------------------------------------------- leer


@lru_cache(maxsize=1)
def _leidos_de_la_base() -> Dict[str, str]:
    from django.db.utils import DatabaseError

    try:
        from .models import AjusteDeLaContabilidad

        return {
            ajuste.clave: ajuste.valor for ajuste in AjusteDeLaContabilidad.objects.all()
        }
    except (DatabaseError, ImportError):  # pragma: no cover - antes de migrar
        return {}


def de_la_base() -> Dict[str, str]:
    """Los valores guardados."""
    return dict(_leidos_de_la_base())


def booleano(clave: str, por_defecto: bool = False) -> bool:
    """Un ajuste sí/no, con su valor de serie si todavía no está en la base."""
    guardado = _leidos_de_la_base().get(clave)
    if guardado is None:
        declarado = _REGISTRO.get(clave)
        if declarado is None:
            return por_defecto
        guardado = declarado.valor
    return str(guardado).strip().lower() in _SI


# ------------------------------------------------------------------ escribir


def poner(clave: str, nuevo: Any) -> None:
    """Guarda un ajuste (lo crea si no está) y refresca lo que se lee."""
    from .models import AjusteDeLaContabilidad

    declarado = _REGISTRO.get(clave)
    if isinstance(nuevo, bool):
        nuevo = "si" if nuevo else "no"
    AjusteDeLaContabilidad.objects.update_or_create(
        clave=clave,
        defaults={
            "valor": str(nuevo),
            "tipo": declarado.tipo if declarado else "texto",
            "grupo": declarado.grupo if declarado else "Contabilidad",
            "descripcion": declarado.descripcion if declarado else "",
            "orden": declarado.orden if declarado else 0,
            "editable": declarado.editable if declarado else True,
        },
    )
    _leidos_de_la_base.cache_clear()


def sembrar(usando: str = "default") -> int:
    """Crea los ajustes declarados que falten. Nunca pisa el valor."""
    from .models import AjusteDeLaContabilidad

    existentes = set(
        AjusteDeLaContabilidad.objects.using(usando).values_list("clave", flat=True)
    )
    creados = 0
    for declarado in _REGISTRO.values():
        if declarado.clave in existentes:
            AjusteDeLaContabilidad.objects.using(usando).filter(clave=declarado.clave).update(
                tipo=declarado.tipo,
                grupo=declarado.grupo,
                descripcion=declarado.descripcion,
                orden=declarado.orden,
                editable=declarado.editable,
            )
            continue
        AjusteDeLaContabilidad.objects.using(usando).create(
            clave=declarado.clave,
            valor=declarado.valor,
            tipo=declarado.tipo,
            grupo=declarado.grupo,
            descripcion=declarado.descripcion,
            orden=declarado.orden,
            editable=declarado.editable,
        )
        creados += 1
    _leidos_de_la_base.cache_clear()
    return creados


def sembrar_al_migrar(
    sender: Any = None, app_config: Any = None, using: str = "default", **kwargs: Any
) -> None:
    """La señal ``post_migrate``: deja los ajustes de serie en la base."""
    sembrar(usando=using)
