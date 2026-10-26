"""La costura entre los comprobantes del SRI y la contabilidad.

Cuando el SRI autoriza un comprobante, aquí se arma su asiento:

* **Factura**: cuentas por cobrar al debe; ventas (bienes o servicios) e IVA por
  pagar al haber. Si el cliente retuvo, la retención queda por cobrar.
* **Nota de crédito**: al revés que la factura.
* **Nota de débito**: cuentas por cobrar al debe; otros ingresos e IVA al haber.
* **Liquidación de compra**: la compra del proveedor, con IVA crédito.
* **Retención**: crea la compra de cada documento sustento (si no estaba) y deja
  el pasivo por la retención de renta, IVA o ISD.

Lo que no venga de un comprobante se escribe a mano con :func:`crear_asiento`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from django.conf import settings
from . import ajustes
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from factec.django.documentos import (
    Factura,
    LiquidacionCompra,
    NotaCredito,
    NotaDebito,
    Retencion,
    TipoProducto,
)
from factec.django.models import ComprobanteEmitido, EstadoComprobante

from .models import (
    CERO,
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    EstadoAsiento,
    LineaAsiento,
    PeriodoContable,
    TipoAsiento,
)

__all__ = [
    "ErrorContable",
    "cerrar_ejercicio",
    "configuracion",
    "contabilizar_compra",
    "contabilizar_comprobante",
    "contabilizar_factura",
    "contabilizar_liquidacion",
    "contabilizar_nota_credito",
    "contabilizar_nota_debito",
    "contabilizar_pendientes",
    "contabilizar_retencion",
    "crear_asiento",
    "periodo_de",
    "reabrir_ejercicio",
]


class ErrorContable(ValidationError):
    """Algo impide contabilizar y hay que decírselo al usuario."""


# ------------------------------------------------------------------ ayudas


def configuracion() -> ConfiguracionContable:
    """La configuración contable activa."""
    config = ConfiguracionContable.activa_actual()
    if config is None:
        raise ErrorContable(
            "No hay configuración contable. Elija las cuentas en «Configuración contable»."
        )
    return config


def cuenta_de(config: ConfiguracionContable, campo: str) -> Cuenta:
    """Una cuenta de la configuración, con un error claro si falta."""
    cuenta = getattr(config, campo, None)
    if cuenta is None:
        nombre = ConfiguracionContable._meta.get_field(campo).verbose_name
        raise ErrorContable(
            f"Falta elegir la cuenta de «{nombre}» en «Configuración contable»."
        )
    return cuenta


def periodo_de(fecha: date) -> PeriodoContable:
    """El periodo abierto de esa fecha; si no hay, se crea el del mes."""
    periodo = (
        PeriodoContable.objects.filter(fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .order_by("-fecha_inicio")
        .first()
    )
    if periodo is not None:
        if not periodo.abierto:
            raise ErrorContable(
                f"El periodo «{periodo.nombre}» está cerrado: no admite movimientos."
            )
        return periodo
    if Asiento.objects.filter(
        origen_tipo="cierre",
        origen_id=fecha.year,
        estado=EstadoAsiento.CONTABILIZADO.value,
    ).exists():
        raise ErrorContable(
            f"El ejercicio {fecha.year} está cerrado: no se pueden crear periodos nuevos."
        )
    if ajustes.booleano("contabilidad_periodo_automatico", True):
        return PeriodoContable.crear_del_mes(fecha.year, fecha.month)
    raise ErrorContable(
        f"No hay un periodo contable para el {fecha:%d/%m/%Y}. Créelo en «Cierre contable»."
    )


def _linea(
    cuenta: Cuenta,
    *,
    debe: Decimal = CERO,
    haber: Decimal = CERO,
    descripcion: str = "",
    tercero: Any = None,
    documento: str = "",
    base_impuesto: str = "",
) -> dict:
    return {
        "cuenta": cuenta,
        "debe": debe,
        "haber": haber,
        "descripcion": descripcion,
        "tercero": tercero,
        "documento": documento,
        "base_impuesto": base_impuesto,
    }


def crear_asiento(
    *,
    fecha: date,
    concepto: str,
    lineas: Iterable[dict],
    tipo: str = TipoAsiento.DIARIO.value,
    referencia: str = "",
    comprobante: Optional[ComprobanteEmitido] = None,
    origen_tipo: str = "manual",
    origen_id: Optional[int] = None,
    usuario: Any = None,
    contabilizar: bool = True,
) -> Optional[Asiento]:
    """Crea un asiento con sus líneas y, si se pide, lo contabiliza.

    Es idempotente por ``origen_tipo``/``origen_id``: si ese comprobante ya tiene
    asiento, devuelve el que hay en vez de duplicarlo.
    """
    if origen_id is not None:
        existente = Asiento.de_origen(origen_tipo, origen_id)
        if existente is not None:
            return existente

    limpias = [
        linea
        for linea in lineas
        if (linea.get("debe") or CERO) or (linea.get("haber") or CERO)
    ]
    if not limpias:
        return None
    if len(limpias) < 2:
        raise ErrorContable("Un asiento necesita al menos dos líneas (debe y haber).")

    with transaction.atomic():
        asiento = Asiento.objects.create(
            fecha=fecha,
            concepto=concepto[:300],
            tipo=tipo,
            referencia=referencia[:120],
            comprobante=comprobante,
            origen_tipo=origen_tipo,
            origen_id=origen_id,
            usuario=usuario,
        )
        LineaAsiento.objects.bulk_create(
            [
                LineaAsiento(
                    asiento=asiento,
                    cuenta=linea["cuenta"],
                    descripcion=(linea.get("descripcion") or "")[:200],
                    debe=linea.get("debe") or CERO,
                    haber=linea.get("haber") or CERO,
                    tercero=linea.get("tercero"),
                    documento=(linea.get("documento") or "")[:30],
                    base_impuesto=linea.get("base_impuesto") or "",
                )
                for linea in limpias
            ]
        )
        if contabilizar:
            asiento.contabilizar(usuario=usuario)
    return asiento


# ------------------------------------------------------ comprobantes del SRI


def contabilizar_comprobante(comprobante: ComprobanteEmitido, usuario: Any = None) -> Optional[Asiento]:
    """Contabiliza el documento que hay detrás de un comprobante autorizado."""
    if comprobante.estado != EstadoComprobante.AUTORIZADO.value:
        return None
    objeto = comprobante.objeto
    if objeto is None:
        return None

    if isinstance(objeto, Factura):
        return contabilizar_factura(objeto, comprobante=comprobante, usuario=usuario)
    if isinstance(objeto, NotaCredito):
        return contabilizar_nota_credito(objeto, comprobante=comprobante, usuario=usuario)
    if isinstance(objeto, NotaDebito):
        return contabilizar_nota_debito(objeto, comprobante=comprobante, usuario=usuario)
    if isinstance(objeto, LiquidacionCompra):
        return contabilizar_liquidacion(objeto, comprobante=comprobante, usuario=usuario)
    if isinstance(objeto, Retencion):
        return contabilizar_retencion(objeto, comprobante=comprobante, usuario=usuario)
    return None


def _referencia(comprobante: Optional[ComprobanteEmitido], respaldo: str = "") -> str:
    if comprobante is not None:
        return f"{comprobante.get_tipo_comprobante_display()} {comprobante.numero_comprobante}"
    return respaldo


def _numero_documento(comprobante: Optional[ComprobanteEmitido], respaldo: str = "") -> str:
    if comprobante is not None:
        return comprobante.numero_comprobante
    return respaldo


def _bases_por_cuenta(factura: Factura, config: ConfiguracionContable) -> dict[Cuenta, Decimal]:
    """Reparte la base de la factura entre ventas de bienes y de servicios."""
    cuentas = defaultdict(lambda: CERO)
    for detalle in factura.detalles.select_related("producto"):
        tipo = getattr(detalle.producto, "tipo", TipoProducto.PRODUCTO.value)
        if tipo == TipoProducto.SERVICIO.value:
            cuenta = cuenta_de(config, "cuenta_ventas_servicios")
        else:
            cuenta = cuenta_de(config, "cuenta_ventas_bienes")
        cuentas[cuenta] += detalle.precio_total_sin_impuesto
    return dict(cuentas)


def contabilizar_factura(
    factura: Factura,
    *,
    comprobante: Optional[ComprobanteEmitido] = None,
    usuario: Any = None,
) -> Optional[Asiento]:
    """Venta: cuentas por cobrar contra ingresos e IVA."""
    config = configuracion()
    cliente_cuenta = cuenta_de(config, "cuenta_clientes")
    iva_cuenta = cuenta_de(config, "cuenta_iva_ventas")
    comprobante = comprobante or factura.comprobante
    documento = _numero_documento(comprobante)
    concepto = f"Venta a {factura.receptor.razon_social}"

    total = factura.total
    iva = factura.valor_iva
    ret_iva = factura.valor_ret_iva or CERO
    ret_renta = factura.valor_ret_renta or CERO
    por_cobrar = total - ret_iva - ret_renta

    lineas = []
    if por_cobrar:
        lineas.append(
            _linea(
                cliente_cuenta, debe=por_cobrar, descripcion=concepto,
                tercero=factura.receptor, documento=documento,
            )
        )
    if ret_iva:
        lineas.append(
            _linea(
                cuenta_de(config, "cuenta_retencion_iva_por_cobrar"),
                debe=ret_iva,
                descripcion="IVA que retiene el cliente",
                tercero=factura.receptor,
                documento=documento,
            )
        )
    if ret_renta:
        lineas.append(
            _linea(
                cuenta_de(config, "cuenta_retencion_renta_por_cobrar"),
                debe=ret_renta,
                descripcion="Renta que retiene el cliente",
                tercero=factura.receptor,
                documento=documento,
            )
        )
    for cuenta, base in _bases_por_cuenta(factura, config).items():
        if base:
            lineas.append(
                _linea(
                    cuenta, haber=base, descripcion=concepto,
                    tercero=factura.receptor, documento=documento,
                )
            )
    if iva:
        lineas.append(
            _linea(
                iva_cuenta, haber=iva, descripcion="IVA de la venta",
                tercero=factura.receptor, documento=documento,
            )
        )

    return crear_asiento(
        fecha=factura.fecha_emision,
        concepto=concepto,
        lineas=lineas,
        tipo=TipoAsiento.VENTA.value,
        referencia=_referencia(comprobante, f"Factura {documento}"),
        comprobante=comprobante,
        origen_tipo="factura",
        origen_id=factura.pk,
        usuario=usuario,
    )


def contabilizar_nota_credito(
    nota: NotaCredito,
    *,
    comprobante: Optional[ComprobanteEmitido] = None,
    usuario: Any = None,
) -> Optional[Asiento]:
    """Devolución: se deshace la venta."""
    config = configuracion()
    cliente_cuenta = cuenta_de(config, "cuenta_clientes")
    iva_cuenta = cuenta_de(config, "cuenta_iva_ventas")
    comprobante = comprobante or nota.comprobante
    documento = _numero_documento(comprobante)
    concepto = f"Nota de crédito a {nota.receptor.razon_social}"

    lineas = []
    for cuenta, base in _bases_por_cuenta(nota, config).items():
        if base:
            lineas.append(
                _linea(
                    cuenta, debe=base, descripcion=concepto,
                    tercero=nota.receptor, documento=documento,
                )
            )
    if nota.valor_iva:
        lineas.append(
            _linea(
                iva_cuenta, debe=nota.valor_iva, descripcion="IVA devuelto",
                tercero=nota.receptor, documento=documento,
            )
        )
    lineas.append(
        _linea(
            cliente_cuenta, haber=nota.total, descripcion=concepto,
            tercero=nota.receptor, documento=documento,
        )
    )

    return crear_asiento(
        fecha=nota.fecha_emision,
        concepto=concepto,
        lineas=lineas,
        tipo=TipoAsiento.VENTA.value,
        referencia=_referencia(comprobante, f"Nota de crédito {documento}"),
        comprobante=comprobante,
        origen_tipo="nota_credito",
        origen_id=nota.pk,
        usuario=usuario,
    )


def contabilizar_nota_debito(
    nota: NotaDebito,
    *,
    comprobante: Optional[ComprobanteEmitido] = None,
    usuario: Any = None,
) -> Optional[Asiento]:
    """Cobro adicional: cuentas por cobrar contra otros ingresos e IVA."""
    config = configuracion()
    comprobante = comprobante or nota.comprobante
    documento = _numero_documento(comprobante)
    concepto = f"Nota de débito a {nota.receptor.razon_social}"

    lineas = [
        _linea(
            cuenta_de(config, "cuenta_clientes"),
            debe=nota.total,
            descripcion=concepto,
            tercero=nota.receptor,
            documento=documento,
        ),
        _linea(
            cuenta_de(config, "cuenta_otros_ingresos"),
            haber=nota.total_sin_impuestos,
            descripcion=concepto,
            tercero=nota.receptor,
            documento=documento,
        ),
    ]
    if nota.valor_iva:
        lineas.append(
            _linea(
                cuenta_de(config, "cuenta_iva_ventas"),
                haber=nota.valor_iva,
                descripcion="IVA de la nota de débito",
                tercero=nota.receptor,
                documento=documento,
            )
        )

    return crear_asiento(
        fecha=nota.fecha_emision,
        concepto=concepto,
        lineas=lineas,
        tipo=TipoAsiento.VENTA.value,
        referencia=_referencia(comprobante, f"Nota de débito {documento}"),
        comprobante=comprobante,
        origen_tipo="nota_debito",
        origen_id=nota.pk,
        usuario=usuario,
    )


def _bases_de_liquidacion(liquidacion: LiquidacionCompra) -> tuple[Decimal, Decimal]:
    """Devuelve (base gravada, base 0 %) de una liquidación de compra."""
    base_iva = CERO
    base_cero = CERO
    for detalle in liquidacion.detalles.all():
        if detalle.tarifa_iva > 0:
            base_iva += detalle.precio_total_sin_impuesto
        else:
            base_cero += detalle.precio_total_sin_impuesto
    return base_iva, base_cero


def contabilizar_liquidacion(
    liquidacion: LiquidacionCompra,
    *,
    comprobante: Optional[ComprobanteEmitido] = None,
    usuario: Any = None,
) -> Optional[Asiento]:
    """La liquidación de compra es una compra: IVA crédito y cuenta por pagar."""
    config = configuracion()
    comprobante = comprobante or liquidacion.comprobante
    numero = (
        comprobante.numero_comprobante.replace("-", "")
        if comprobante is not None
        else ""
    )
    if not numero:
        return None
    base_iva, base_cero = _bases_de_liquidacion(liquidacion)
    compra, creada = Compra.objects.get_or_create(
        proveedor=liquidacion.proveedor,
        tipo_comprobante=liquidacion.tipo_comprobante,
        numero=numero,
        defaults={
            "fecha": liquidacion.fecha_emision,
            "concepto": f"Liquidación de compra a {liquidacion.proveedor.razon_social}",
            "autorizacion": comprobante.clave_acceso if comprobante is not None else "",
            "cod_sustento": "01",
            "base_iva": base_iva,
            "base_iva_0": base_cero,
            "valor_iva": liquidacion.valor_iva,
            "total": liquidacion.total,
            "cuenta": config.cuenta_compras_gastos,
            "periodo": periodo_de(liquidacion.fecha_emision),
        },
    )
    if not creada and compra.cuenta_id is None:
        compra.cuenta = config.cuenta_compras_gastos
        compra.save(update_fields=["cuenta", "actualizado"])
    return contabilizar_compra(compra, usuario=usuario, comprobante=comprobante)


def contabilizar_compra(
    compra: Compra,
    *,
    usuario: Any = None,
    comprobante: Optional[ComprobanteEmitido] = None,
) -> Optional[Asiento]:
    """Compra: gasto o inventario + IVA crédito contra proveedores."""
    if compra.asiento_id and compra.asiento and compra.asiento.estado != EstadoAsiento.ANULADO.value:
        return compra.asiento
    config = configuracion()
    cuenta = compra.cuenta or config.cuenta_compras_gastos or config.cuenta_inventario
    if cuenta is None:
        raise ErrorContable(
            "La compra no dice a qué cuenta va y no hay una cuenta de compras configurada."
        )
    documento = compra.numero_con_guiones
    concepto = compra.concepto or f"Compra a {compra.proveedor.razon_social}"

    base_gasto = (
        compra.base_no_grava + compra.base_exenta + compra.base_iva_0
        + compra.base_iva + compra.propina
    )
    # Solo el sustento 01 da derecho a crédito tributario de IVA. En los demás,
    # el IVA es parte del costo o gasto (y si no es deducible, de la cuenta 5.3.10).
    iva_al_credito = compra.valor_iva if compra.cod_sustento == "01" else CERO
    iva_al_gasto = compra.valor_iva - iva_al_credito
    lineas = [
        _linea(
            cuenta, debe=base_gasto + iva_al_gasto, descripcion=concepto,
            tercero=compra.proveedor, documento=documento,
        )
    ]
    if iva_al_credito:
        lineas.append(
            _linea(
                cuenta_de(config, "cuenta_iva_compras"),
                debe=iva_al_credito,
                descripcion="IVA crédito tributario",
                tercero=compra.proveedor,
                documento=documento,
            )
        )
    lineas.append(
        _linea(
            cuenta_de(config, "cuenta_proveedores"),
            haber=compra.total,
            descripcion=concepto,
            tercero=compra.proveedor,
            documento=documento,
        )
    )

    asiento = crear_asiento(
        fecha=compra.fecha,
        concepto=concepto,
        lineas=lineas,
        tipo=TipoAsiento.COMPRA.value,
        referencia=f"Compra {documento}",
        comprobante=comprobante,
        origen_tipo="compra",
        origen_id=compra.pk,
        usuario=usuario,
    )
    if asiento is not None:
        compra.asiento = asiento
        compra.save(update_fields=["asiento", "actualizado"])
    return asiento


def _datos_de_compra_desde_sustento(
    retencion: Retencion, documento: Any, config: ConfiguracionContable
) -> dict[str, Any]:
    """Traduce el documento sustento del SRI a una compra del negocio."""
    base_iva = CERO
    base_cero = CERO
    base_no_grava = CERO
    base_exenta = CERO
    iva = CERO
    for impuesto in documento.impuestos.all():
        tarifa = impuesto.tarifa or CERO
        codigo = str(impuesto.codigo_porcentaje or "")
        if tarifa > 0:
            base_iva += impuesto.base_imponible
        elif codigo == "7":
            base_exenta += impuesto.base_imponible
        elif codigo == "6":
            base_no_grava += impuesto.base_imponible
        else:
            base_cero += impuesto.base_imponible
        iva += impuesto.valor
    base_conocida = base_iva + base_cero + base_no_grava + base_exenta
    no_grava = max(CERO, (documento.total_sin_impuestos or CERO) - base_conocida)
    return {
        "proveedor": retencion.sujeto_retenido,
        "tipo_comprobante": documento.cod_doc_sustento,
        "cod_sustento": documento.cod_sustento,
        "numero": "".join(c for c in documento.num_doc_sustento if c.isdigit()),
        "autorizacion": documento.num_aut_doc_sustento,
        "fecha": documento.fecha_emision,
        "concepto": f"Compra a {retencion.sujeto_retenido.razon_social}",
        "base_no_grava": base_no_grava + no_grava,
        "base_exenta": base_exenta,
        "base_iva_0": base_cero,
        "base_iva": base_iva,
        "valor_iva": iva,
        "total": documento.importe_total,
        "cuenta": config.cuenta_compras_gastos,
        "retencion": retencion,
        "periodo": periodo_de(documento.fecha_emision),
    }


def contabilizar_retencion(
    retencion: Retencion,
    *,
    comprobante: Optional[ComprobanteEmitido] = None,
    usuario: Any = None,
) -> Optional[Asiento]:
    """Retención emitida al proveedor.

    Primero deja registrada la compra de cada documento sustento (si no estaba) y
    contabiliza su asiento; después deja el pasivo de lo retenido y rebaja la
    cuenta por pagar del proveedor.
    """
    config = configuracion()
    comprobante = comprobante or retencion.comprobante
    documento = _numero_documento(comprobante)

    total_retenido = CERO
    por_cuenta: dict[Cuenta, Decimal] = defaultdict(lambda: CERO)

    for sustento in retencion.docs_sustento.prefetch_related("impuestos", "retenciones"):
        datos = _datos_de_compra_desde_sustento(retencion, sustento, config)
        if not datos["numero"]:
            continue
        compra, creada = Compra.objects.get_or_create(
            proveedor=datos["proveedor"],
            tipo_comprobante=datos["tipo_comprobante"],
            numero=datos["numero"],
            defaults=datos,
        )
        if not creada and compra.retencion_id is None:
            compra.retencion = retencion
            compra.save(update_fields=["retencion", "actualizado"])
        contabilizar_compra(compra, usuario=usuario)

        for aplicada in sustento.retenciones.all():
            total_retenido += aplicada.valor_retenido
            if aplicada.codigo == "2":
                cuenta = cuenta_de(config, "cuenta_retencion_iva_por_pagar")
            elif aplicada.codigo == "6":
                cuenta = (
                    config.cuenta_retencion_isd_por_pagar
                    or cuenta_de(config, "cuenta_retencion_renta_por_pagar")
                )
            else:
                cuenta = cuenta_de(config, "cuenta_retencion_renta_por_pagar")
            por_cuenta[cuenta] += aplicada.valor_retenido

    if not total_retenido:
        return None

    concepto = f"Retención a {retencion.sujeto_retenido.razon_social}"
    lineas = [
        _linea(
            cuenta_de(config, "cuenta_proveedores"),
            debe=total_retenido,
            descripcion=concepto,
            tercero=retencion.sujeto_retenido,
            documento=documento,
        )
    ]
    for cuenta, valor in por_cuenta.items():
        if valor:
            lineas.append(
                _linea(
                    cuenta,
                    haber=valor,
                    descripcion=concepto,
                    tercero=retencion.sujeto_retenido,
                    documento=documento,
                )
            )

    return crear_asiento(
        fecha=retencion.fecha_emision,
        concepto=concepto,
        lineas=lineas,
        tipo=TipoAsiento.RETENCION.value,
        referencia=_referencia(comprobante, f"Retención {documento}"),
        comprobante=comprobante,
        origen_tipo="retencion",
        origen_id=retencion.pk,
        usuario=usuario,
    )


def contabilizar_pendientes(usuario: Any = None) -> dict[str, Any]:
    """Contabiliza los comprobantes autorizados que quedaron sin asiento.

    Sirve para cuando la emisión la hizo el worker o el admin. Devuelve cuántos
    se contabilizaron y los errores que hubo, para enseñarlos.
    """
    hechos = 0
    errores: list[str] = []
    comprobantes = (
        ComprobanteEmitido.objects.filter(estado=EstadoComprobante.AUTORIZADO.value)
        .order_by("fecha_emision", "pk")
    )
    for comprobante in comprobantes:
        try:
            asiento = contabilizar_comprobante(comprobante, usuario=usuario)
        except Exception as error:  # noqa: BLE001 - se informa, no se corta el lote
            errores.append(f"{comprobante}: {error}")
            continue
        if asiento is not None:
            hechos += 1
    return {"contabilizados": hechos, "errores": errores}


# ------------------------------------------------------------------- cierre


def cerrar_ejercicio(anio: int, usuario: Any = None) -> Optional[Asiento]:
    """Cierra el ejercicio: lleva ingresos y gastos al resultado y este a acumulados.

    El asiento se hace con fecha 31 de diciembre. Después, todos los periodos del
    año quedan cerrados y no admiten movimientos.
    """
    config = configuracion()
    cuenta_resultado = cuenta_de(config, "cuenta_resultado_ejercicio")
    cuenta_acumulados = cuenta_de(config, "cuenta_resultados_acumulados")

    if Asiento.de_origen("cierre", anio) is not None:
        raise ErrorContable(f"El ejercicio {anio} ya está cerrado.")

    desde = date(anio, 1, 1)
    hasta = date(anio, 12, 31)
    movimientos = (
        LineaAsiento.objects.filter(
            asiento__estado=EstadoAsiento.CONTABILIZADO.value,
            asiento__fecha__gte=desde,
            asiento__fecha__lte=hasta,
        )
        .exclude(asiento__tipo=TipoAsiento.CIERRE.value)
        .values("cuenta__tipo", "cuenta__codigo", "cuenta__nombre", "cuenta_id")
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )

    lineas: list[dict] = []
    resultado = CERO
    for fila in movimientos:
        tipo = fila["cuenta__tipo"]
        neto = (fila["debe"] or CERO) - (fila["haber"] or CERO)
        cuenta = Cuenta.objects.get(pk=fila["cuenta_id"])
        if tipo == "ingreso":
            saldo = -neto  # acreedora
            if saldo:
                resultado += saldo
                if saldo > 0:
                    lineas.append(_linea(cuenta, debe=saldo, descripcion=f"Cierre {anio}"))
                else:
                    lineas.append(
                        _linea(cuenta, haber=-saldo, descripcion=f"Cierre {anio}")
                    )
        elif tipo in ("costo", "gasto"):
            saldo = neto  # deudora
            if saldo:
                resultado -= saldo
                if saldo > 0:
                    lineas.append(_linea(cuenta, haber=saldo, descripcion=f"Cierre {anio}"))
                else:
                    lineas.append(
                        _linea(cuenta, debe=-saldo, descripcion=f"Cierre {anio}")
                    )

    if not lineas:
        raise ErrorContable(f"El ejercicio {anio} no tiene ingresos ni gastos que cerrar.")

    if resultado > 0:
        lineas.append(
            _linea(cuenta_resultado, haber=resultado, descripcion=f"Utilidad {anio}")
        )
        lineas.append(
            _linea(cuenta_resultado, debe=resultado, descripcion=f"Utilidad {anio}")
        )
        lineas.append(
            _linea(cuenta_acumulados, haber=resultado, descripcion=f"Utilidad {anio}")
        )
    elif resultado < 0:
        perdida = -resultado
        lineas.append(
            _linea(cuenta_resultado, debe=perdida, descripcion=f"Pérdida {anio}")
        )
        lineas.append(
            _linea(cuenta_resultado, haber=perdida, descripcion=f"Pérdida {anio}")
        )
        lineas.append(
            _linea(cuenta_acumulados, debe=perdida, descripcion=f"Pérdida {anio}")
        )

    asiento = crear_asiento(
        fecha=hasta,
        concepto=f"Cierre del ejercicio {anio}",
        lineas=lineas,
        tipo=TipoAsiento.CIERRE.value,
        referencia=f"Cierre {anio}",
        origen_tipo="cierre",
        origen_id=anio,
        usuario=usuario,
    )
    if asiento is not None:
        PeriodoContable.objects.filter(ejercicio=anio).update(estado=PeriodoContable.Estado.CERRADO.value)
    return asiento


def reabrir_ejercicio(anio: int, usuario: Any = None) -> None:
    """Reabre un año cerrado: anula el asiento de cierre y abre sus periodos."""
    asiento = Asiento.objects.filter(
        origen_tipo="cierre", origen_id=anio, estado=EstadoAsiento.CONTABILIZADO.value
    ).first()
    if asiento is not None:
        asiento.anular("Reapertura del ejercicio", usuario=usuario)
    PeriodoContable.objects.filter(ejercicio=anio).update(
        estado=PeriodoContable.Estado.ABIERTO.value
    )
