"""Contabiliza los comprobantes autorizados que quedaron pendientes."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from conta_ec.django import servicios


class Command(BaseCommand):
    help = "Contabiliza las facturas y comprobantes autorizados que no tienen asiento."

    def handle(self, *args, **options) -> None:
        resultado = servicios.contabilizar_pendientes()
        self.stdout.write(
            self.style.SUCCESS(
                f"{resultado['contabilizados']} comprobantes contabilizados."
            )
        )
        for error in resultado["errores"]:
            self.stderr.write(self.style.WARNING(error))
