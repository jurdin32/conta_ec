"""Siembra el plan de cuentas NIIF y la configuración contable."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from conta_ec.django import plan


class Command(BaseCommand):
    help = "Crea el plan de cuentas inicial y deja la configuración contable lista."

    def handle(self, *args, **options) -> None:
        creadas, existentes = plan.sembrar()
        self.stdout.write(
            self.style.SUCCESS(
                f"Plan de cuentas: {creadas} cuentas creadas, {existentes} ya existían."
            )
        )
