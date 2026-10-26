"""El plan de cuentas inicial, basado en la estructura NIIF de la Superintendencia.

No es una camisa de fuerza: la Superintendencia de Compañías exige estados
financieros bajo NIIF y un plan de cuentas coherente, no unos códigos únicos para
todas las empresas. Este catálogo sigue los cinco grandes grupos (activo, pasivo,
patrimonio, ingresos y costos/gastos) y se puede cambiar desde «Plan de cuentas».

Las cuentas de corrección llevan la naturaleza contraria a su grupo:
depreciación acumulada y amortización acumulada son acreedoras; descuentos y
devoluciones en ventas y pérdidas acumuladas son deudoras.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = ["CUENTAS", "MAPA_INICIAL", "sembrar"]

#: (código, nombre, grupo, naturaleza). Sin naturaleza se toma la del grupo.
CUENTAS: tuple[tuple[str, str, str, Optional[str]], ...] = (
    ("1", "Activo", "activo", None),
    ("1.1", "Activo corriente", "activo", None),
    ("1.1.01", "Efectivo y equivalentes del efectivo", "activo", None),
    ("1.1.01.01", "Caja", "activo", None),
    ("1.1.01.02", "Bancos", "activo", None),
    ("1.1.01.03", "Caja chica", "activo", None),
    ("1.1.02", "Activos financieros", "activo", None),
    ("1.1.02.01", "Cuentas por cobrar clientes", "activo", None),
    ("1.1.02.02", "Documentos por cobrar", "activo", None),
    ("1.1.02.03", "Retenciones de IVA por cobrar", "activo", None),
    ("1.1.02.04", "Retenciones de renta por cobrar", "activo", None),
    ("1.1.02.05", "Otras cuentas por cobrar", "activo", None),
    ("1.1.03", "Inventarios", "activo", None),
    ("1.1.03.01", "Inventario de mercaderías", "activo", None),
    ("1.1.03.02", "Inventario de materias primas", "activo", None),
    ("1.1.03.03", "Inventario de productos terminados", "activo", None),
    ("1.1.04", "Activos por impuestos corrientes", "activo", None),
    ("1.1.04.01", "IVA crédito tributario", "activo", None),
    ("1.1.04.02", "Crédito tributario a favor", "activo", None),
    ("1.1.04.03", "Anticipo de impuesto a la renta", "activo", None),
    ("1.1.05", "Gastos pagados por anticipado", "activo", None),
    ("1.1.05.01", "Seguros prepagados", "activo", None),
    ("1.1.05.02", "Arriendos prepagados", "activo", None),
    ("1.1.06", "Otros activos corrientes", "activo", None),
    ("1.1.06.01", "Materiales y suministros", "activo", None),
    ("1.1.06.02", "Depósitos en garantía", "activo", None),
    ("1.2", "Activo no corriente", "activo", None),
    ("1.2.01", "Propiedad, planta y equipo", "activo", None),
    ("1.2.01.01", "Muebles y enseres", "activo", None),
    ("1.2.01.02", "Maquinaria y equipo", "activo", None),
    ("1.2.01.03", "Vehículos", "activo", None),
    ("1.2.01.04", "Equipo de computación", "activo", None),
    ("1.2.01.05", "Edificios", "activo", None),
    ("1.2.01.06", "Terrenos", "activo", None),
    ("1.2.02", "Depreciación acumulada", "activo", "acreedora"),
    ("1.2.02.01", "Depreciación acumulada de propiedad, planta y equipo", "activo", "acreedora"),
    ("1.2.03", "Activos intangibles", "activo", None),
    ("1.2.03.01", "Software", "activo", None),
    ("1.2.03.02", "Amortización acumulada de activos intangibles", "activo", "acreedora"),

    ("2", "Pasivo", "pasivo", None),
    ("2.1", "Pasivo corriente", "pasivo", None),
    ("2.1.01", "Cuentas por pagar proveedores", "pasivo", None),
    ("2.1.02", "Documentos por pagar", "pasivo", None),
    ("2.1.03", "Obligaciones con el IESS", "pasivo", None),
    ("2.1.04", "Sueldos y beneficios por pagar", "pasivo", None),
    ("2.1.05", "Impuestos por pagar", "pasivo", None),
    ("2.1.05.01", "IVA por pagar", "pasivo", None),
    ("2.1.05.02", "Retenciones de renta por pagar", "pasivo", None),
    ("2.1.05.03", "Retenciones de IVA por pagar", "pasivo", None),
    ("2.1.05.04", "ISD por pagar", "pasivo", None),
    ("2.1.05.05", "Impuesto a la renta por pagar", "pasivo", None),
    ("2.1.05.06", "ICE por pagar", "pasivo", None),
    ("2.1.06", "Provisiones corrientes", "pasivo", None),
    ("2.1.06.01", "Beneficios sociales por pagar", "pasivo", None),
    ("2.1.06.02", "Provisiones laborales", "pasivo", None),
    ("2.2", "Pasivo no corriente", "pasivo", None),
    ("2.2.01", "Obligaciones financieras a largo plazo", "pasivo", None),
    ("2.2.02", "Cuentas por pagar a largo plazo", "pasivo", None),

    ("3", "Patrimonio", "patrimonio", None),
    ("3.1", "Capital", "patrimonio", None),
    ("3.1.01", "Capital social", "patrimonio", None),
    ("3.1.02", "Aportes de socios", "patrimonio", None),
    ("3.2", "Reservas", "patrimonio", None),
    ("3.2.01", "Reserva legal", "patrimonio", None),
    ("3.2.02", "Reservas estatutarias", "patrimonio", None),
    ("3.3", "Resultados", "patrimonio", None),
    ("3.3.01", "Resultados acumulados", "patrimonio", None),
    ("3.3.02", "Resultado del ejercicio", "patrimonio", None),
    ("3.3.03", "Pérdidas acumuladas", "patrimonio", "deudora"),

    ("4", "Ingresos", "ingreso", None),
    ("4.1", "Ingresos de actividades ordinarias", "ingreso", None),
    ("4.1.01", "Ventas de bienes", "ingreso", None),
    ("4.1.02", "Prestación de servicios", "ingreso", None),
    ("4.1.03", "Intereses y rendimientos", "ingreso", None),
    ("4.1.04", "Otros ingresos de actividades ordinarias", "ingreso", None),
    ("4.2", "Otros ingresos", "ingreso", None),
    ("4.2.01", "Utilidad en venta de activos", "ingreso", None),
    ("4.2.02", "Arriendos cobrados", "ingreso", None),
    ("4.2.03", "Otros ingresos", "ingreso", None),
    ("4.3", "Descuentos y devoluciones en ventas", "ingreso", "deudora"),
    ("4.3.01", "Descuentos y devoluciones en ventas", "ingreso", "deudora"),

    ("5", "Costos y gastos", "gasto", None),
    ("5.1", "Costos", "costo", None),
    ("5.1.01", "Costo de ventas", "costo", None),
    ("5.1.02", "Costo de servicios", "costo", None),
    ("5.1.03", "Mano de obra directa", "costo", None),
    ("5.1.04", "Costos indirectos de fabricación", "costo", None),
    ("5.1.05", "Compras", "costo", None),
    ("5.2", "Gastos de venta", "gasto", None),
    ("5.2.01", "Sueldos y salarios de ventas", "gasto", None),
    ("5.2.02", "Beneficios sociales y aportes", "gasto", None),
    ("5.2.03", "Honorarios profesionales", "gasto", None),
    ("5.2.04", "Publicidad y promoción", "gasto", None),
    ("5.2.05", "Comisiones", "gasto", None),
    ("5.2.06", "Transporte y flete", "gasto", None),
    ("5.3", "Gastos administrativos", "gasto", None),
    ("5.3.01", "Sueldos y salarios administrativos", "gasto", None),
    ("5.3.02", "Arrendamiento", "gasto", None),
    ("5.3.03", "Servicios básicos", "gasto", None),
    ("5.3.04", "Suministros y materiales", "gasto", None),
    ("5.3.05", "Mantenimiento y reparaciones", "gasto", None),
    ("5.3.06", "Depreciación", "gasto", None),
    ("5.3.07", "Amortización", "gasto", None),
    ("5.3.08", "Seguros", "gasto", None),
    ("5.3.09", "Impuestos, contribuciones y tasas", "gasto", None),
    ("5.3.10", "Gastos no deducibles", "gasto", None),
    ("5.3.11", "Otros gastos administrativos", "gasto", None),
    ("5.4", "Gastos financieros", "gasto", None),
    ("5.4.01", "Intereses y comisiones bancarias", "gasto", None),
    ("5.4.02", "Diferencia en cambio", "gasto", None),
    ("5.5", "Impuesto a la renta", "gasto", None),
    ("5.5.01", "Gasto por impuesto a la renta", "gasto", None),
)

#: Qué cuenta se propone para cada operación automática de la configuración.
MAPA_INICIAL = {
    "cuenta_caja": "1.1.01.01",
    "cuenta_banco": "1.1.01.02",
    "cuenta_clientes": "1.1.02.01",
    "cuenta_retencion_iva_por_cobrar": "1.1.02.03",
    "cuenta_retencion_renta_por_cobrar": "1.1.02.04",
    "cuenta_inventario": "1.1.03.01",
    "cuenta_iva_compras": "1.1.04.01",
    "cuenta_proveedores": "2.1.01",
    "cuenta_iess_por_pagar": "2.1.03",
    "cuenta_iva_ventas": "2.1.05.01",
    "cuenta_retencion_renta_por_pagar": "2.1.05.02",
    "cuenta_retencion_iva_por_pagar": "2.1.05.03",
    "cuenta_retencion_isd_por_pagar": "2.1.05.04",
    "cuenta_reserva_legal": "3.2.01",
    "cuenta_resultados_acumulados": "3.3.01",
    "cuenta_resultado_ejercicio": "3.3.02",
    "cuenta_ventas_bienes": "4.1.01",
    "cuenta_ventas_servicios": "4.1.02",
    "cuenta_otros_ingresos": "4.2.03",
    "cuenta_descuentos_ventas": "4.3.01",
    "cuenta_costo_ventas": "5.1.01",
    "cuenta_compras_gastos": "5.1.05",
    "cuenta_impuesto_renta": "5.5.01",
}


NATURALEZA_POR_TIPO = {
    "activo": "deudora",
    "pasivo": "acreedora",
    "patrimonio": "acreedora",
    "ingreso": "acreedora",
    "costo": "deudora",
    "gasto": "deudora",
}


def sembrar(
    Cuenta: Any = None,
    ConfiguracionContable: Any = None,
) -> tuple[int, int]:
    """Crea las cuentas que falten y deja la configuración contable apuntando a ellas.

    Es idempotente: si una cuenta ya existe no le cambia el nombre ni la naturaleza,
    para no pisar lo que el negocio haya ajustado. Se puede llamar desde una
    migración de datos o desde el comando ``sembrar_plan_cuentas``.
    """
    if Cuenta is None or ConfiguracionContable is None:
        from .models import ConfiguracionContable as ConfigActual
        from .models import Cuenta as CuentaActual

        Cuenta = CuentaActual
        ConfiguracionContable = ConfigActual

    creadas = 0
    existentes = 0
    por_codigo: dict[str, Any] = {
        cuenta.codigo: cuenta for cuenta in Cuenta.objects.all()
    }
    for codigo, nombre, tipo, naturaleza in sorted(
        CUENTAS, key=lambda fila: (fila[0].count("."), fila[0])
    ):
        if codigo in por_codigo:
            existentes += 1
            continue
        padre = None
        if "." in codigo:
            padre = por_codigo.get(codigo.rsplit(".", 1)[0])
        cuenta = Cuenta.objects.create(
            codigo=codigo,
            nombre=nombre,
            tipo=tipo,
            naturaleza=naturaleza or NATURALEZA_POR_TIPO[tipo],
            padre=padre,
            nivel=codigo.count(".") + 1,
            permite_movimientos=False if any(
                otra[0].startswith(codigo + ".") for otra in CUENTAS
            ) else True,
        )
        por_codigo[codigo] = cuenta
        creadas += 1

    # Las madres nunca reciben asientos.
    for codigo, cuenta in por_codigo.items():
        if any(otro != codigo and otro.startswith(codigo + ".") for otro in por_codigo):
            if cuenta.permite_movimientos:
                cuenta.permite_movimientos = False
                cuenta.save(update_fields=["permite_movimientos"])

    config = ConfiguracionContable.objects.filter(activa=True).order_by("-pk").first()
    if config is None:
        config = ConfiguracionContable.objects.create(
            nombre="Contabilidad principal", activa=True
        )
    cambios = []
    for campo, codigo in MAPA_INICIAL.items():
        cuenta = por_codigo.get(codigo)
        if cuenta is not None and getattr(config, f"{campo}_id", None) is None:
            setattr(config, campo, cuenta)
            cambios.append(campo)
    if cambios:
        config.save(update_fields=cambios + ["actualizado"])
    return creadas, existentes
