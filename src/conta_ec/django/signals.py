"""Contabilización automática cuando el SRI autoriza un comprobante.

En vez de depender de la pantalla que emitió (la web, el admin o el worker de
Celery), se escucha el cambio de estado del ``ComprobanteEmitido``. Así una factura
autorizada se contabiliza siempre, venga de donde venga.

Si algo falla (por ejemplo, porque todavía no se eligieron las cuentas), **no se
rompe la emisión**: se deja el error en el registro y el comprobante se puede
contabilizar después con «Contabilizar pendientes».
"""

from __future__ import annotations

import logging

from django.conf import settings
from . import ajustes
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from factec.django.models import ComprobanteEmitido, EstadoComprobante

__all__ = ["contabilizar_al_autorizar", "recordar_estado_anterior"]

registro = logging.getLogger(__name__)


@receiver(pre_save, sender=ComprobanteEmitido)
def recordar_estado_anterior(sender, instance: ComprobanteEmitido, **kwargs) -> None:
    """Guarda el estado que tenía antes de guardarse, para detectar la transición."""
    instance._estado_anterior = None
    if instance.pk:
        instance._estado_anterior = (
            ComprobanteEmitido.objects.filter(pk=instance.pk)
            .values_list("estado", flat=True)
            .first()
        )


@receiver(post_save, sender=ComprobanteEmitido)
def contabilizar_al_autorizar(
    sender, instance: ComprobanteEmitido, created: bool, **kwargs
) -> None:
    """Al pasar a AUTORIZADO, arma su asiento."""
    if not ajustes.booleano("contabilidad_contabilizar_al_autorizar", True):
        return
    if instance.estado != EstadoComprobante.AUTORIZADO.value:
        return
    anterior = getattr(instance, "_estado_anterior", None)
    if not created and anterior == EstadoComprobante.AUTORIZADO.value:
        return

    from . import servicios

    try:
        servicios.contabilizar_comprobante(instance)
    except Exception:  # noqa: BLE001 - la emisión no se puede caer por la contabilidad
        registro.exception(
            "No se pudo contabilizar el comprobante %s", instance.numero_comprobante
        )
