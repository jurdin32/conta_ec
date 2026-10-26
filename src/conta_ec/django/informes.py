"""Los libros y los estados financieros, calculados desde los asientos.

Todo se lee de las líneas contabilizadas: los borradores no cuentan y los asientos
anulados tampoco. Los informes se pueden pedir por rango de fechas, que es lo que
necesita el contador para el mes, el trimestre o el ejercicio.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from django.db.models import Sum
from factec.catalogos import PORCENTAJE_IVA
from factec.django.documentos import (
    Factura,
    LiquidacionCompra,
    NotaCredito,
    NotaDebito,
    Retencion,
)
from factec.django.models import EstadoComprobante

from .models import (
    CERO,
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    EstadoAsiento,
    LineaAsiento,
    Naturaleza,
    TipoAsiento,
    TipoCuenta,
)

__all__ = [
    "balance_comprobacion",
    "bases_por_tarifa",
    "documentos_compra",
    "documentos_venta",
    "estado_flujos",
    "estado_patrimonio",
    "estado_resultados",
    "estado_situacion",
    "libro_diario",
    "libro_mayor",
    "registro_compras",
    "registro_ventas",
    "resumen_ats",
    "resumen_iva",
    "resumen_retenciones",
    "retenciones_del_mes",
]


# ------------------------------------------------------------------ lectura


def _lineas(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    *,
    incluir_cierre: bool = True,
) -> Any:
    consulta = LineaAsiento.objects.filter(
        asiento__estado=EstadoAsiento.CONTABILIZADO.value
    )
    if desde:
        consulta = consulta.filter(asiento__fecha__gte=desde)
    if hasta:
        consulta = consulta.filter(asiento__fecha__lte=hasta)
    if not incluir_cierre:
        consulta = consulta.exclude(asiento__tipo=TipoAsiento.CIERRE.value)
    return consulta


def _saldos(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    *,
    incluir_cierre: bool = True,
) -> dict[int, tuple[Decimal, Decimal]]:
    """(debe, haber) de cada cuenta, sumando solo sus movimientos directos."""
    filas = (
        _lineas(desde, hasta, incluir_cierre=incluir_cierre)
        .values("cuenta_id")
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
    )
    return {
        fila["cuenta_id"]: (fila["debe"] or CERO, fila["haber"] or CERO)
        for fila in filas
    }


def _cuentas() -> list[Cuenta]:
    return list(Cuenta.objects.all().order_by("codigo"))


def _agregados(saldos: dict[int, tuple[Decimal, Decimal]]) -> dict[int, tuple[Decimal, Decimal]]:
    """Suma a cada cuenta madre lo de sus hijas (de abajo hacia arriba)."""
    totales = {pk: list(valores) for pk, valores in saldos.items()}
    for cuenta in _cuentas():
        totales.setdefault(cuenta.pk, [CERO, CERO])
    for cuenta in sorted(_cuentas(), key=lambda c: c.codigo, reverse=True):
        if cuenta.padre_id:
            totales[cuenta.padre_id][0] += totales[cuenta.pk][0]
            totales[cuenta.padre_id][1] += totales[cuenta.pk][1]
    return {pk: (valores[0], valores[1]) for pk, valores in totales.items()}


def _fila(cuenta: Cuenta, debe: Decimal, haber: Decimal) -> dict:
    saldo = debe - haber
    return {
        "cuenta": cuenta,
        "codigo": cuenta.codigo,
        "nombre": cuenta.nombre,
        "nivel": cuenta.nivel,
        "debe": debe,
        "haber": haber,
        "saldo": saldo,
        "saldo_deudor": saldo if saldo > 0 else CERO,
        "saldo_acreedor": -saldo if saldo < 0 else CERO,
    }


# ------------------------------------------------------------ libro diario


def libro_diario(desde: date, hasta: date) -> dict[str, Any]:
    """Los asientos del rango, con sus líneas, en orden cronológico."""
    asientos = (
        Asiento.objects.filter(
            estado=EstadoAsiento.CONTABILIZADO.value,
            fecha__gte=desde,
            fecha__lte=hasta,
        )
        .prefetch_related("lineas__cuenta")
        .order_by("fecha", "numero", "pk")
    )
    filas = []
    total_debe = CERO
    total_haber = CERO
    for asiento in asientos:
        lineas = list(asiento.lineas.all())
        debe = sum((linea.debe for linea in lineas), CERO)
        haber = sum((linea.haber for linea in lineas), CERO)
        total_debe += debe
        total_haber += haber
        filas.append(
            {"asiento": asiento, "lineas": lineas, "debe": debe, "haber": haber}
        )
    return {
        "filas": filas,
        "total_debe": total_debe,
        "total_haber": total_haber,
        "cuantos": len(filas),
    }


def libro_mayor(cuenta: Cuenta, desde: date, hasta: date) -> dict[str, Any]:
    """El extracto de una cuenta: saldo anterior, movimientos y saldo final."""
    saldo_anterior = cuenta.saldo_para_balance(hasta=desde - _un_dia())
    movimientos = (
        LineaAsiento.objects.filter(
            cuenta=cuenta,
            asiento__estado=EstadoAsiento.CONTABILIZADO.value,
            asiento__fecha__gte=desde,
            asiento__fecha__lte=hasta,
        )
        .select_related("asiento", "tercero")
        .order_by("asiento__fecha", "asiento__numero", "pk")
    )
    filas = []
    saldo = saldo_anterior
    total_debe = CERO
    total_haber = CERO
    for linea in movimientos:
        saldo += linea.debe - linea.haber
        total_debe += linea.debe
        total_haber += linea.haber
        filas.append(
            {
                "linea": linea,
                "asiento": linea.asiento,
                "debe": linea.debe,
                "haber": linea.haber,
                "saldo": saldo,
            }
        )
    return {
        "cuenta": cuenta,
        "desde": desde,
        "hasta": hasta,
        "saldo_anterior": saldo_anterior,
        "filas": filas,
        "total_debe": total_debe,
        "total_haber": total_haber,
        "saldo_final": saldo,
    }


def _un_dia():
    from datetime import timedelta

    return timedelta(days=1)


# ------------------------------------------------------------- balance


def balance_comprobacion(desde: date, hasta: date) -> dict[str, Any]:
    """Sumas y saldos por cuenta, con las madres sumando a sus hijas."""
    directos = _saldos(desde, hasta)
    totales = _agregados(directos)
    filas = []
    for cuenta in _cuentas():
        debe, haber = totales.get(cuenta.pk, (CERO, CERO))
        propios = directos.get(cuenta.pk, (CERO, CERO))
        if not (debe or haber or propios[0] or propios[1]):
            continue
        fila = _fila(cuenta, debe, haber)
        fila["propios"] = propios[0] or propios[1]
        fila["es_madre"] = cuenta.hijas.exists()
        filas.append(fila)
    return {
        "filas": filas,
        "total_debe": sum((fila["debe"] for fila in filas if not fila["es_madre"]), CERO),
        "total_haber": sum((fila["haber"] for fila in filas if not fila["es_madre"]), CERO),
    }


# ------------------------------------------------------- estado de resultados


def estado_resultados(desde: date, hasta: date) -> dict[str, Any]:
    """Ingresos, costos y gastos del rango, sin contar el asiento de cierre."""
    directos = _saldos(desde, hasta, incluir_cierre=False)
    cuentas = {cuenta.pk: cuenta for cuenta in _cuentas()}

    secciones = {"ingreso": [], "costo": [], "gasto": []}
    totales = {"ingreso": CERO, "costo": CERO, "gasto": CERO}
    for pk, (debe, haber) in directos.items():
        cuenta = cuentas.get(pk)
        if cuenta is None or cuenta.tipo not in secciones:
            continue
        if cuenta.tipo == TipoCuenta.INGRESO.value:
            valor = haber - debe
        else:
            valor = debe - haber
        if not valor:
            continue
        fila = _fila(cuenta, debe, haber)
        fila["valor"] = valor
        secciones[cuenta.tipo].append(fila)
        totales[cuenta.tipo] += valor

    for filas in secciones.values():
        filas.sort(key=lambda fila: fila["codigo"])

    utilidad_bruta = totales["ingreso"] - totales["costo"]
    resultado = utilidad_bruta - totales["gasto"]
    return {
        "desde": desde,
        "hasta": hasta,
        "ingresos": secciones["ingreso"],
        "costos": secciones["costo"],
        "gastos": secciones["gasto"],
        "total_ingresos": totales["ingreso"],
        "total_costos": totales["costo"],
        "total_gastos": totales["gasto"],
        "utilidad_bruta": utilidad_bruta,
        "resultado": resultado,
        "es_utilidad": resultado >= 0,
    }


# ---------------------------------------------------- estado de situación


def estado_situacion(hasta: date) -> dict[str, Any]:
    """Activo, pasivo y patrimonio al cierre de una fecha."""
    directos = _saldos(hasta=hasta)
    totales = _agregados(directos)
    cuentas = _cuentas()
    secciones = {"activo": [], "pasivo": [], "patrimonio": []}
    sumas = {"activo": CERO, "pasivo": CERO, "patrimonio": CERO}

    for cuenta in cuentas:
        if cuenta.tipo not in secciones:
            continue
        debe, haber = totales.get(cuenta.pk, (CERO, CERO))
        bruto = debe - haber
        if cuenta.tipo == TipoCuenta.ACTIVO.value:
            valor = bruto
        else:
            valor = -bruto
        if not valor:
            continue
        fila = _fila(cuenta, debe, haber)
        fila["valor"] = valor
        fila["es_madre"] = cuenta.hijas.exists()
        secciones[cuenta.tipo].append(fila)
        if not fila["es_madre"]:
            sumas[cuenta.tipo] += valor

    # El resultado del ejercicio que todavía no se ha cerrado. Si ya se cerró, las
    # cuentas de ingreso y gasto están en cero y no se suma nada.
    ingresos = _saldos(hasta=hasta, incluir_cierre=True)
    por_pk = {cuenta.pk: cuenta for cuenta in cuentas}
    resultado = CERO
    for pk, (debe, haber) in ingresos.items():
        cuenta = por_pk.get(pk)
        if cuenta is None:
            continue
        if cuenta.tipo == TipoCuenta.INGRESO.value:
            resultado += haber - debe
        elif cuenta.tipo in (TipoCuenta.COSTO.value, TipoCuenta.GASTO.value):
            resultado -= debe - haber

    # El resultado del ejercicio todavía no está en una cuenta de patrimonio, pero
    # forma parte de él: el total tiene que incluirlo para que el balance cuadre.
    total_patrimonio = sumas["patrimonio"] + resultado
    total_pasivo_patrimonio = sumas["pasivo"] + total_patrimonio
    return {
        "hasta": hasta,
        "activo": secciones["activo"],
        "pasivo": secciones["pasivo"],
        "patrimonio": secciones["patrimonio"],
        "total_activo": sumas["activo"],
        "total_pasivo": sumas["pasivo"],
        "total_patrimonio": total_patrimonio,
        "resultado": resultado,
        "total_pasivo_patrimonio": total_pasivo_patrimonio,
        "diferencia": sumas["activo"] - total_pasivo_patrimonio,
    }


# ------------------------------------------------------- flujos de efectivo


def _cuentas_de_efectivo(config: ConfiguracionContable) -> list[Cuenta]:
    cuentas = []
    for base in (config.cuenta_caja, config.cuenta_banco):
        if base is not None:
            cuentas.extend(base.descendientes())
    vistos = {}
    for cuenta in cuentas:
        vistos[cuenta.pk] = cuenta
    return list(vistos.values())


def estado_flujos(desde: date, hasta: date, config: ConfiguracionContable) -> dict[str, Any]:
    """Flujo de efectivo por el método directo, agrupado por actividad.

    Se mira cada asiento que toca caja o bancos y se clasifica por la contrapartida:
    operación (ingresos, gastos, cartera), inversión (activo no corriente) o
    financiación (pasivo no corriente y patrimonio).
    """
    efectivo = _cuentas_de_efectivo(config)
    ids_efectivo = {cuenta.pk for cuenta in efectivo}
    saldo_inicial = sum(
        (cuenta.saldo_para_balance(hasta=desde - _un_dia()) for cuenta in efectivo), CERO
    )

    asientos = (
        Asiento.objects.filter(
            estado=EstadoAsiento.CONTABILIZADO.value,
            fecha__gte=desde,
            fecha__lte=hasta,
            lineas__cuenta_id__in=ids_efectivo,
        )
        .distinct()
        .prefetch_related("lineas__cuenta")
        .order_by("fecha", "numero")
    )

    grupos = {
        "operacion": {"nombre": "Actividades de operación", "filas": [], "total": CERO},
        "inversion": {"nombre": "Actividades de inversión", "filas": [], "total": CERO},
        "financiacion": {"nombre": "Actividades de financiación", "filas": [], "total": CERO},
    }
    for asiento in asientos:
        lineas = list(asiento.lineas.all())
        efectivo_de_asiento = sum(
            (linea.debe - linea.haber for linea in lineas if linea.cuenta_id in ids_efectivo),
            CERO,
        )
        if not efectivo_de_asiento:
            continue
        otras = [linea for linea in lineas if linea.cuenta_id not in ids_efectivo]
        grupo = _grupo_de_flujo(otras)
        # El detalle se agrupa por la contrapartida principal, para que el informe
        # se lea como un estado y no como un volcado de asientos.
        contraparte = otras[0].cuenta if otras else None
        etiqueta = asiento.concepto
        if contraparte is not None:
            etiqueta = f"{asiento.concepto} · {contraparte.codigo} {contraparte.nombre}"
        grupos[grupo]["filas"].append(
            {
                "asiento": asiento,
                "concepto": etiqueta,
                "fecha": asiento.fecha,
                "valor": efectivo_de_asiento,
            }
        )
        grupos[grupo]["total"] += efectivo_de_asiento

    total = sum((grupo["total"] for grupo in grupos.values()), CERO)
    return {
        "desde": desde,
        "hasta": hasta,
        "saldo_inicial": saldo_inicial,
        "grupos": [grupo for grupo in grupos.values() if grupo["filas"]],
        "total": total,
        "saldo_final": saldo_inicial + total,
    }


def _grupo_de_flujo(otras: Iterable[LineaAsiento]) -> str:
    for linea in otras:
        cuenta = linea.cuenta
        if cuenta.tipo in (TipoCuenta.INGRESO.value, TipoCuenta.COSTO.value, TipoCuenta.GASTO.value):
            return "operacion"
        if cuenta.tipo == TipoCuenta.ACTIVO.value and cuenta.codigo.startswith("1.2"):
            return "inversion"
        if cuenta.tipo in (TipoCuenta.PASIVO.value, TipoCuenta.PATRIMONIO.value):
            return "financiacion"
    return "operacion"


# ------------------------------------------------------ cambios en el patrimonio


def estado_patrimonio(desde: date, hasta: date) -> dict[str, Any]:
    """Movimientos del patrimonio en el rango, con su saldo inicial y final."""
    cuentas = [c for c in _cuentas() if c.tipo == TipoCuenta.PATRIMONIO.value]
    antes = _saldos(hasta=desde - _un_dia())
    durante = _saldos(desde, hasta)
    filas = []
    totales = {"inicial": CERO, "aumentos": CERO, "disminuciones": CERO, "final": CERO}
    for cuenta in cuentas:
        if cuenta.hijas.exists():
            continue
        debe_antes, haber_antes = antes.get(cuenta.pk, (CERO, CERO))
        debe, haber = durante.get(cuenta.pk, (CERO, CERO))
        inicial = haber_antes - debe_antes
        aumentos = haber
        disminuciones = debe
        final = inicial + aumentos - disminuciones
        if not (inicial or aumentos or disminuciones):
            continue
        filas.append(
            {
                "cuenta": cuenta,
                "inicial": inicial,
                "aumentos": aumentos,
                "disminuciones": disminuciones,
                "final": final,
            }
        )
        totales["inicial"] += inicial
        totales["aumentos"] += aumentos
        totales["disminuciones"] += disminuciones
        totales["final"] += final

    # Resultado del ejercicio que aún no está en una cuenta de patrimonio.
    resultado = estado_resultados(desde, hasta)["resultado"]
    if resultado:
        filas.append(
            {
                "cuenta": None,
                "nombre": "Resultado del ejercicio",
                "inicial": CERO,
                "aumentos": resultado if resultado > 0 else CERO,
                "disminuciones": -resultado if resultado < 0 else CERO,
                "final": resultado,
                "es_resultado": True,
            }
        )
        totales["aumentos"] += resultado if resultado > 0 else CERO
        totales["disminuciones"] += -resultado if resultado < 0 else CERO
        totales["final"] += resultado

    return {"desde": desde, "hasta": hasta, "filas": filas, "totales": totales}


# -------------------------------------------------------- documentos del SRI


def documentos_venta(anio: int, mes: int) -> list[tuple[str, Any]]:
    """Facturas, notas de crédito y de débito autorizadas en el mes."""
    filtro = {
        "comprobante__estado": EstadoComprobante.AUTORIZADO.value,
        "fecha_emision__year": anio,
        "fecha_emision__month": mes,
    }
    documentos = [
        ("factura", factura) for factura in Factura.objects.filter(**filtro).select_related("receptor")
    ]
    documentos += [
        ("nota_credito", nota)
        for nota in NotaCredito.objects.filter(**filtro).select_related("receptor")
    ]
    documentos += [
        ("nota_debito", nota)
        for nota in NotaDebito.objects.filter(**filtro).select_related("receptor")
    ]
    documentos.sort(key=lambda par: (par[1].fecha_emision, par[1].pk))
    return documentos


def documentos_compra(anio: int, mes: int):
    return Compra.objects.filter(fecha__year=anio, fecha__month=mes).select_related(
        "proveedor", "retencion"
    )


def retenciones_del_mes(anio: int, mes: int):
    return (
        Retencion.objects.filter(
            comprobante__estado=EstadoComprobante.AUTORIZADO.value,
            fecha_emision__year=anio,
            fecha_emision__month=mes,
        )
        .select_related("sujeto_retenido")
        .prefetch_related("docs_sustento__impuestos", "docs_sustento__retenciones")
    )


def bases_por_tarifa(documento: Any) -> dict[str, Decimal]:
    """Separa la base de un comprobante en 0 %, gravada y exenta, con su IVA."""
    datos = {"base_0": CERO, "base_gravada": CERO, "base_exenta": CERO, "iva": CERO}
    if hasattr(documento, "detalles"):
        for detalle in documento.detalles.all():
            base = detalle.precio_total_sin_impuesto
            codigo = str(detalle.codigo_porcentaje_iva)
            tarifa = PORCENTAJE_IVA.get(codigo, CERO)
            if tarifa > 0:
                datos["base_gravada"] += base
            elif codigo in ("6", "7"):
                datos["base_exenta"] += base
            else:
                datos["base_0"] += base
        datos["iva"] = documento.valor_iva
    else:
        base = documento.total_sin_impuestos
        tarifa = PORCENTAJE_IVA.get(str(documento.codigo_porcentaje_iva), CERO)
        if tarifa > 0:
            datos["base_gravada"] = base
        else:
            datos["base_0"] = base
        datos["iva"] = documento.valor_iva
    return datos


# ------------------------------------------------------------- IVA y retenciones


def resumen_iva(anio: int, mes: int) -> dict[str, Any]:
    """Resumen para el formulario 104: ventas, compras e IVA del mes."""
    ventas = {"base_0": CERO, "base_gravada": CERO, "base_exenta": CERO, "iva": CERO}
    retenido_por_clientes = CERO
    for clase, documento in documentos_venta(anio, mes):
        datos = bases_por_tarifa(documento)
        signo = -1 if clase == "nota_credito" else 1
        for clave in ventas:
            ventas[clave] += datos[clave] * signo
        retenido_por_clientes += (getattr(documento, "valor_ret_iva", CERO) or CERO) * signo

    compras = {"base_0": CERO, "base_gravada": CERO, "base_exenta": CERO, "iva": CERO}
    for compra in documentos_compra(anio, mes):
        compras["base_0"] += compra.base_iva_0
        compras["base_gravada"] += compra.base_iva
        compras["base_exenta"] += compra.base_no_grava + compra.base_exenta
        # Solo el sustento 01 genera crédito tributario de IVA.
        if compra.cod_sustento == "01":
            compras["iva"] += compra.valor_iva

    ret_iva = CERO
    ret_renta = CERO
    for retencion in retenciones_del_mes(anio, mes):
        for sustento in retencion.docs_sustento.all():
            for aplicada in sustento.retenciones.all():
                if aplicada.codigo == "2":
                    ret_iva += aplicada.valor_retenido
                elif aplicada.codigo == "1":
                    ret_renta += aplicada.valor_retenido

    retencion_iva = ret_iva + retenido_por_clientes
    return {
        "anio": anio,
        "mes": mes,
        "ventas": ventas,
        "compras": compras,
        "retencion_iva": retencion_iva,
        "retencion_iva_efectuada": ret_iva,
        "retencion_iva_recibida": retenido_por_clientes,
        "retencion_renta": ret_renta,
        "iva_por_pagar": ventas["iva"] - compras["iva"] - retencion_iva,
        "total_ventas": ventas["base_0"] + ventas["base_gravada"] + ventas["base_exenta"] + ventas["iva"],
        "total_compras": compras["base_0"] + compras["base_gravada"] + compras["base_exenta"] + compras["iva"],
    }


def resumen_retenciones(anio: int, mes: int) -> dict[str, Any]:
    """Retenciones del mes agrupadas por impuesto y código (formulario 103)."""
    filas: dict[tuple[str, str], dict[str, Any]] = {}
    total = CERO
    for retencion in retenciones_del_mes(anio, mes):
        for sustento in retencion.docs_sustento.all():
            for aplicada in sustento.retenciones.all():
                clave = (aplicada.codigo, aplicada.codigo_retencion)
                fila = filas.setdefault(
                    clave,
                    {
                        "codigo": aplicada.codigo,
                        "codigo_retencion": aplicada.codigo_retencion,
                        "base": CERO,
                        "valor": CERO,
                        "cuantas": 0,
                        "porcentaje": aplicada.porcentaje_retener,
                    },
                )
                fila["base"] += aplicada.base_imponible
                fila["valor"] += aplicada.valor_retenido
                fila["cuantas"] += 1
                total += aplicada.valor_retenido
    return {
        "anio": anio,
        "mes": mes,
        "filas": sorted(filas.values(), key=lambda f: (f["codigo"], f["codigo_retencion"])),
        "total": total,
    }


def resumen_ats(anio: int, mes: int) -> dict[str, Any]:
    """Los números que irán al ATS, para poder revisarlos antes de descargarlo."""
    documentos = documentos_venta(anio, mes)
    total_ventas = CERO
    for clase, documento in documentos:
        signo = -1 if clase == "nota_credito" else 1
        total_ventas += documento.total * signo
    compras = documentos_compra(anio, mes)
    return {
        "ventas": len(documentos),
        "compras": compras.count(),
        "retenciones": retenciones_del_mes(anio, mes).count(),
        "total_ventas": total_ventas,
        "total_compras": sum((compra.total for compra in compras), CERO),
    }


# ------------------------------------------------------- registros exportables


def registro_ventas(anio: int, mes: int) -> list[dict[str, Any]]:
    """Filas del registro de ventas, con el formato que se entrega al SRI."""
    filas = []
    for clase, documento in documentos_venta(anio, mes):
        datos = bases_por_tarifa(documento)
        signo = -1 if clase == "nota_credito" else 1
        filas.append(
            {
                "tipo": clase,
                "comprobante": documento.descripcion_tipo,
                "numero": _numero_de(documento),
                "fecha": documento.fecha_emision,
                "identificacion": documento.receptor.identificacion,
                "razon_social": documento.receptor.razon_social,
                "base_0": datos["base_0"] * signo,
                "base_gravada": datos["base_gravada"] * signo,
                "base_exenta": datos["base_exenta"] * signo,
                "iva": datos["iva"] * signo,
                "total": documento.total * signo,
            }
        )
    return filas


def registro_compras(anio: int, mes: int) -> list[dict[str, Any]]:
    """Filas del registro de compras."""
    filas = []
    for compra in documentos_compra(anio, mes):
        filas.append(
            {
                "tipo": "compra",
                "comprobante": compra.get_tipo_comprobante_display(),
                "numero": compra.numero_con_guiones,
                "fecha": compra.fecha,
                "identificacion": compra.proveedor.identificacion,
                "razon_social": compra.proveedor.razon_social,
                "base_0": compra.base_iva_0,
                "base_gravada": compra.base_iva,
                "base_exenta": compra.base_no_grava + compra.base_exenta,
                "iva": compra.valor_iva,
                "total": compra.total,
            }
        )
    return filas


def _numero_de(documento: Any) -> str:
    comprobante = getattr(documento, "comprobante", None)
    if comprobante is not None:
        return comprobante.numero_comprobante
    return getattr(documento, "secuencial", "") or ""
