"""Anexos que se presentan al SRI, generados desde los comprobantes y la contabilidad.

**ATS** — Anexo Transaccional Simplificado. Se arma con el XSD oficial
``ats.xsd`` del SRI (Resolución NAC-DGERCGC12-00001 y sus reformas): compras,
ventas, retenciones y ventas por establecimiento. Las fechas van como
``DD/MM/AAAA`` y los importes con punto decimal y dos decimales, tal como los
valida el esquema.

**RDEP** — Anexo de Retenciones en la Fuente bajo Relación de Dependencia. Se
arma con el XSD oficial ``Esquema RDEP 2023.xsd`` (artículo 43 de la LORTI y
Resolución NAC-DGERCGC24-00000002). Es un anexo **anual** por empleado.

**REOC** — Anexo de Retenciones en la Fuente por Otros Conceptos. Se arma con
``reoc.xsd`` y lleva, por cada compra, las retenciones de renta aplicadas.

El sistema no inventa datos: si falta la autorización de una compra o un campo
obligatorio del RDEP, la generación se detiene y se dice exactamente qué falta.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional
from xml.etree import ElementTree as ET

from django.core.exceptions import ValidationError
from factec.django import conf
from factec.django.models import EstadoComprobante

from . import informes
from .models import CERO, Compra, ConfiguracionContable, Empleado

__all__ = [
    "ErrorAnexo",
    "generar_ats_xml",
    "generar_csv_compras_ventas",
    "generar_rdep_xml",
    "generar_reoc_xml",
]


class ErrorAnexo(ValidationError):
    """Falta un dato o no cumple el esquema del SRI."""


#: Retenciones de IVA de la tabla 20 del SRI y el campo del ATS que las recibe.
#: Los códigos son los que admite el comprobante de retención (comprobados contra el
#: servicio de autorización del SRI): no son los 721/723/725 de otras tablas.
RETENCIONES_IVA_ATS = {
    "1": "valorRetBienes",       # 30 % bienes
    "2": "valorRetServicios",    # 70 % servicios
    "3": "valRetServ100",        # 100 % servicios
    "9": "valRetBien10",         # 10 % bienes
    "10": "valRetServ20",        # 20 % servicios
    "11": "valRetServ50",        # 50 % servicios
}


# ------------------------------------------------------------------ formatos


def _importe(valor: Any) -> str:
    """Importe con punto decimal y dos decimales, como lo exige el SRI."""
    numero = Decimal(valor or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{numero:.2f}"


def _fecha(valor: Optional[date]) -> str:
    """El SRI pide las fechas como DD/MM/AAAA, no en ISO."""
    if valor is None:
        raise ErrorAnexo("Falta una fecha obligatoria para el anexo.")
    return valor.strftime("%d/%m/%Y")


def _entero(valor: Any) -> str:
    return str(int(valor or 0))


def _agregar(padre: ET.Element, etiqueta: str, valor: Any) -> ET.Element:
    hijo = ET.SubElement(padre, etiqueta)
    hijo.text = str(valor)
    return hijo


def _sin_acentos(texto: str) -> str:
    """El XSD del RDEP solo admite letras sin tilde, espacios y nada más."""
    normalizado = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in normalizado if not unicodedata.combining(c))
    limpio = re.sub(r"[^A-Za-z ]", "", sin_tildes)
    return re.sub(r"\s+", " ", limpio).strip()


def _emisor() -> Any:
    emisor = conf.configuracion_activa()
    if emisor is None:
        raise ErrorAnexo(
            "No hay configuración del emisor. Cárguela en «Configuración del SRI»."
        )
    ruc = "".join(c for c in (emisor.ruc or "") if c.isdigit())
    if len(ruc) != 13:
        raise ErrorAnexo("El RUC del emisor debe tener 13 dígitos para presentar anexos.")
    if not (len(emisor.estab or "") == 3 and str(emisor.estab).isdigit()):
        raise ErrorAnexo("El establecimiento del emisor debe ser de tres dígitos (001…).")
    return emisor


def _ruc(emisor: Any) -> str:
    return "".join(c for c in (emisor.ruc or "") if c.isdigit())


def _periodo(anio: int, mes: int) -> None:
    if not (2000 <= int(anio) <= 9999):
        raise ErrorAnexo("El año del anexo debe estar entre 2000 y 9999.")
    if not (1 <= int(mes) <= 12):
        raise ErrorAnexo("El mes del anexo debe estar entre 1 y 12.")


def _xml(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _autorizacion_de(comprobante: Any) -> str:
    if comprobante is None:
        raise ErrorAnexo("El comprobante no tiene registro electrónico autorizado.")
    autorizacion = (
        getattr(comprobante, "numero_autorizacion", "")
        or getattr(comprobante, "clave_acceso", "")
    )
    limpia = "".join(c for c in str(autorizacion) if c.isdigit())
    if not (3 <= len(limpia) <= 49):
        raise ErrorAnexo(
            f"El comprobante {comprobante.numero_comprobante} no tiene un número de "
            "autorización válido (3 a 49 dígitos)."
        )
    return limpia


def _partes_del_numero(numero: str) -> tuple[str, str, str]:
    limpio = "".join(c for c in (numero or "") if c.isdigit())
    if len(limpio) != 15:
        raise ErrorAnexo(
            f"El número «{numero}» no tiene 15 dígitos: no se puede separar en "
            "establecimiento, punto de emisión y secuencial."
        )
    return limpio[:3], limpio[3:6], limpio[6:]


# ---------------------------------------------------------------------- ATS


def _bases_ats(documento: Any) -> dict[str, Decimal]:
    """Reparte la base de una venta en los campos que admite el ATS.

    El ATS de ventas no tiene ``baseImpExe``: lo exento y lo no objeto van a
    ``baseNoGraIva``; el 0 % va a ``baseImponible``; lo gravado a ``baseImpGrav``.
    """
    datos = {
        "baseNoGraIva": CERO,
        "baseImponible": CERO,
        "baseImpGrav": CERO,
        "baseImpExe": CERO,
    }
    if hasattr(documento, "detalles"):
        for detalle in documento.detalles.all():
            base = detalle.precio_total_sin_impuesto
            codigo = str(detalle.codigo_porcentaje_iva)
            tarifa = detalle.tarifa_iva
            if tarifa > 0:
                datos["baseImpGrav"] += base
            elif codigo == "7":
                datos["baseImpExe"] += base
            elif codigo == "6":
                datos["baseNoGraIva"] += base
            else:
                datos["baseImponible"] += base
    else:
        base = documento.total_sin_impuestos
        if documento.tarifa_iva > 0:
            datos["baseImpGrav"] = base
        else:
            datos["baseImponible"] = base
    return datos


def _pago_exterior(padre: ET.Element) -> None:
    """Pago local: es lo normal y lo que el esquema exige si se informa."""
    pago = ET.SubElement(padre, "pagoExterior")
    _agregar(pago, "pagoLocExt", "01")
    _agregar(pago, "aplicConvDobTrib", "NO")
    _agregar(pago, "pagExtSujRetNorLeg", "NO")


def _formas_de_pago(padre: ET.Element, forma: str) -> None:
    formas = ET.SubElement(padre, "formasDePago")
    _agregar(formas, "formaPago", forma or "01")


def _retencion_de_compra(compra: Compra) -> tuple[dict[str, Decimal], Any]:
    """Lo retenido de IVA en la compra y la retención que lo respalda."""
    valores = {campo: CERO for campo in RETENCIONES_IVA_ATS.values()}
    retencion = compra.retencion
    if retencion is None:
        return valores, None
    for sustento in retencion.docs_sustento.all():
        numero = "".join(c for c in (sustento.num_doc_sustento or "") if c.isdigit())
        if numero != compra.numero:
            continue
        for aplicada in sustento.retenciones.all():
            if aplicada.codigo != "2":       # solo IVA; la renta va al REOC
                continue
            campo = RETENCIONES_IVA_ATS.get(str(aplicada.codigo_retencion))
            if campo:
                valores[campo] += aplicada.valor_retenido
    return valores, retencion


def _detalle_compra(compra: Compra) -> ET.Element:
    detalle = ET.Element("detalleCompras")
    establecimiento, punto, secuencial = _partes_del_numero(compra.numero)
    autorizacion = "".join(c for c in (compra.autorizacion or "") if c.isdigit())
    if not (3 <= len(autorizacion) <= 49):
        raise ErrorAnexo(
            f"La compra {compra.numero_con_guiones} de {compra.proveedor.razon_social} "
            "no tiene número de autorización: el ATS no se puede presentar."
        )
    retenciones, retencion = _retencion_de_compra(compra)

    _agregar(detalle, "codSustento", compra.cod_sustento or "01")
    _agregar(detalle, "tpIdProv", compra.proveedor.tipo_identificacion)
    _agregar(detalle, "idProv", compra.proveedor.identificacion)
    _agregar(detalle, "tipoComprobante", compra.tipo_comprobante)
    _agregar(detalle, "parteRel", "NO")
    _agregar(detalle, "fechaRegistro", _fecha(compra.fecha))
    _agregar(detalle, "establecimiento", establecimiento)
    _agregar(detalle, "puntoEmision", punto)
    _agregar(detalle, "secuencial", secuencial)
    _agregar(detalle, "fechaEmision", _fecha(compra.fecha))
    _agregar(detalle, "autorizacion", autorizacion)
    _agregar(detalle, "baseNoGraIva", _importe(compra.base_no_grava))
    _agregar(detalle, "baseImponible", _importe(compra.base_iva_0))
    _agregar(detalle, "baseImpGrav", _importe(compra.base_iva))
    _agregar(detalle, "baseImpExe", _importe(compra.base_exenta))
    _agregar(detalle, "montoIce", _importe(0))
    _agregar(detalle, "montoIva", _importe(compra.valor_iva))
    for campo in (
        "valRetBien10",
        "valRetServ20",
        "valorRetBienes",
        "valRetServ50",
        "valorRetServicios",
        "valRetServ100",
    ):
        _agregar(detalle, campo, _importe(retenciones.get(campo, CERO)))
    _agregar(detalle, "valorRetencionNc", _importe(0))
    _agregar(detalle, "totbasesImpReemb", _importe(0))
    _pago_exterior(detalle)
    _formas_de_pago(detalle, compra.forma_pago)

    # Referencia a la retención que se emitió al proveedor, si la hay.
    if retencion is not None and retencion.comprobante_id:
        comprobante = retencion.comprobante
        _agregar(detalle, "estabRetencion1", comprobante.estab)
        _agregar(detalle, "ptoEmiRetencion1", comprobante.pto_emi)
        _agregar(detalle, "secRetencion1", comprobante.secuencial)
        _agregar(detalle, "autRetencion1", _autorizacion_de(comprobante))
        _agregar(detalle, "fechaEmiRet1", _fecha(retencion.fecha_emision))
    return detalle


def _detalle_venta(clase: str, documento: Any) -> ET.Element:
    comprobante = documento.comprobante
    if comprobante is None:
        raise ErrorAnexo(f"El documento {documento} no está autorizado por el SRI.")
    bases = _bases_ats(documento)
    detalle = ET.Element("detalleVentas")
    _agregar(detalle, "tpIdCliente", documento.receptor.tipo_identificacion)
    _agregar(detalle, "idCliente", documento.receptor.identificacion)
    _agregar(detalle, "parteRelVtas", "NO")
    _agregar(detalle, "tipoComprobante", documento.tipo_comprobante)
    _agregar(detalle, "tipoEmision", "E")
    _agregar(detalle, "numeroComprobantes", "1")
    _agregar(
        detalle,
        "baseNoGraIva",
        _importe(bases["baseNoGraIva"] + bases["baseImpExe"]),
    )
    _agregar(detalle, "baseImponible", _importe(bases["baseImponible"]))
    _agregar(detalle, "baseImpGrav", _importe(bases["baseImpGrav"]))
    _agregar(detalle, "montoIva", _importe(documento.valor_iva))
    _agregar(detalle, "valorRetIva", _importe(getattr(documento, "valor_ret_iva", CERO)))
    _agregar(detalle, "valorRetRenta", _importe(getattr(documento, "valor_ret_renta", CERO)))
    _formas_de_pago(detalle, str(getattr(documento, "forma_pago", "01") or "01"))
    return detalle


def construir_ats(anio: int, mes: int) -> ET.Element:
    """Arma el ``<iva>`` del ATS con el orden de elementos del XSD oficial."""
    _periodo(anio, mes)
    emisor = _emisor()
    documentos = informes.documentos_venta(anio, mes)
    compras = list(informes.documentos_compra(anio, mes))

    total_ventas = CERO
    for clase, documento in documentos:
        total_ventas += documento.total * (-1 if clase == "nota_credito" else 1)

    root = ET.Element("iva")
    _agregar(root, "TipoIDInformante", "R")
    _agregar(root, "IdInformante", _ruc(emisor))
    _agregar(root, "razonSocial", emisor.razon_social)
    _agregar(root, "Anio", _entero(anio))
    _agregar(root, "Mes", f"{int(mes):02d}")
    _agregar(root, "numEstabRuc", emisor.estab)
    _agregar(root, "totalVentas", _importe(total_ventas))
    _agregar(root, "codigoOperativo", "IVA")

    nodo_compras = ET.SubElement(root, "compras")
    for compra in compras:
        nodo_compras.append(_detalle_compra(compra))

    nodo_ventas = ET.SubElement(root, "ventas")
    for clase, documento in documentos:
        nodo_ventas.append(_detalle_venta(clase, documento))

    if documentos:
        establecimientos: dict[str, dict[str, Decimal]] = {}
        for clase, documento in documentos:
            estab = documento.comprobante.estab if documento.comprobante else emisor.estab
            signo = -1 if clase == "nota_credito" else 1
            fila = establecimientos.setdefault(
                estab, {"ventas": CERO, "iva": CERO}
            )
            fila["ventas"] += documento.total * signo
            fila["iva"] += documento.valor_iva * signo
        nodo_establecimientos = ET.SubElement(root, "ventasEstablecimiento")
        for estab, valores in sorted(establecimientos.items()):
            venta = ET.SubElement(nodo_establecimientos, "ventaEst")
            _agregar(venta, "codEstab", estab)
            _agregar(venta, "ventasEstab", _importe(valores["ventas"]))
            _agregar(venta, "ivaComp", _importe(valores["iva"]))
    return root


def generar_ats_xml(anio: int, mes: int) -> bytes:
    """Devuelve el ATS del mes listo para presentar."""
    return _xml(construir_ats(anio, mes))


# --------------------------------------------------------------------- REOC


def construir_reoc(anio: int, mes: int) -> ET.Element:
    """Arma el REOC con las retenciones de renta de las compras del mes."""
    _periodo(anio, mes)
    emisor = _emisor()
    root = ET.Element("reoc")
    _agregar(root, "numeroRuc", _ruc(emisor))
    _agregar(root, "anio", _entero(anio))
    _agregar(root, "mes", f"{int(mes):02d}")
    nodo_compras = ET.SubElement(root, "compras")

    for retencion in informes.retenciones_del_mes(anio, mes):
        comprobante_retencion = retencion.comprobante
        for sustento in retencion.docs_sustento.all():
            renta = [r for r in sustento.retenciones.all() if r.codigo == "1"]
            if not renta:
                continue
            establecimiento, punto, secuencial = _partes_del_numero(
                sustento.num_doc_sustento
            )
            autorizacion = "".join(
                c for c in (sustento.num_aut_doc_sustento or "") if c.isdigit()
            )
            if not (3 <= len(autorizacion) <= 49):
                raise ErrorAnexo(
                    f"La compra {sustento.num_doc_sustento} de "
                    f"{retencion.sujeto_retenido.razon_social} no tiene autorización: "
                    "el REOC no se puede presentar."
                )
            detalle = ET.SubElement(nodo_compras, "detalleCompras")
            _agregar(detalle, "tpIdProv", retencion.sujeto_retenido.tipo_identificacion)
            _agregar(detalle, "idProv", retencion.sujeto_retenido.identificacion)
            _agregar(detalle, "tipoComp", sustento.cod_doc_sustento)
            _agregar(detalle, "aut", autorizacion)
            _agregar(detalle, "estab", establecimiento)
            _agregar(detalle, "ptoEmi", punto)
            _agregar(detalle, "sec", secuencial)
            _agregar(detalle, "fechaEmiCom", _fecha(sustento.fecha_emision))
            if comprobante_retencion is not None:
                _agregar(detalle, "autRet", _autorizacion_de(comprobante_retencion))
                _agregar(detalle, "estabRet", comprobante_retencion.estab)
                _agregar(detalle, "ptoEmiRet", comprobante_retencion.pto_emi)
                _agregar(detalle, "secRet", comprobante_retencion.secuencial)
                _agregar(detalle, "fechaEmiRet", _fecha(retencion.fecha_emision))
            air = ET.SubElement(detalle, "air")
            for aplicada in renta:
                item = ET.SubElement(air, "detalleAir")
                _agregar(item, "codRetAir", aplicada.codigo_retencion)
                _agregar(item, "porcentaje", _importe(aplicada.porcentaje_retener))
                _agregar(item, "base0", _importe(0))
                _agregar(item, "baseGrav", _importe(aplicada.base_imponible))
                _agregar(item, "baseNoGrav", _importe(0))
                _agregar(item, "valRetAir", _importe(aplicada.valor_retenido))
    return root


def generar_reoc_xml(anio: int, mes: int) -> bytes:
    """Devuelve el REOC del mes listo para presentar."""
    return _xml(construir_reoc(anio, mes))


# --------------------------------------------------------------------- RDEP


def _configuracion_rdep() -> ConfiguracionContable:
    config = ConfiguracionContable.activa_actual()
    if config is None:
        raise ErrorAnexo(
            "No hay configuración contable. Elija las cuentas y el tipo de empleador "
            "en «Configuración contable»."
        )
    return config


def _verificar_empleado(empleado: Empleado) -> None:
    faltas = []
    if not empleado.identificacion:
        faltas.append("identificación (idRet)")
    if not empleado.apellidos:
        faltas.append("apellidos (apellidoTrab)")
    if not empleado.nombres:
        faltas.append("nombres (nombreTrab)")
    if not empleado.establecimiento:
        faltas.append("establecimiento (estab)")
    if faltas:
        raise ErrorAnexo(
            f"El empleado {empleado} no tiene {', '.join(faltas)}: el RDEP no se puede generar."
        )
    for etiqueta, valor in (("apellidos", empleado.apellidos), ("nombres", empleado.nombres)):
        limpio = _sin_acentos(valor)
        if not (2 <= len(limpio) <= 100):
            raise ErrorAnexo(
                f"Los {etiqueta} de {empleado} no cumplen el esquema del RDEP: "
                "deben quedar entre 2 y 100 letras."
            )


def _empleado_rdep(padre: ET.Element, empleado: Empleado) -> None:
    """Bloque ``empleado`` (``datEmpTyp``) en el orden del XSD."""
    _verificar_empleado(empleado)
    nodo = ET.SubElement(padre, "empleado")
    _agregar(nodo, "benGalpg", empleado.ben_galpg)
    if empleado.enf_catastro:
        _agregar(nodo, "enfcatastro", empleado.enf_catastro)
    if empleado.num_carg_reb_gast_pers:
        _agregar(nodo, "numCargRebGastPers", _entero(empleado.num_carg_reb_gast_pers))
    _agregar(nodo, "tipIdRet", empleado.tipo_identificacion)
    _agregar(nodo, "idRet", empleado.identificacion)
    _agregar(nodo, "apellidoTrab", _sin_acentos(empleado.apellidos))
    _agregar(nodo, "nombreTrab", _sin_acentos(empleado.nombres))
    _agregar(nodo, "estab", empleado.establecimiento)
    _agregar(nodo, "residenciaTrab", empleado.residencia)
    _agregar(nodo, "paisResidencia", empleado.pais_residencia)
    _agregar(nodo, "aplicaConvenio", empleado.aplica_convenio)
    _agregar(nodo, "tipoTrabajDiscap", empleado.tipo_trabaj_discap)
    _agregar(nodo, "porcentajeDiscap", _entero(empleado.porcentaje_discap))
    _agregar(nodo, "tipIdDiscap", empleado.tip_id_discap)
    if empleado.id_discap:
        _agregar(nodo, "idDiscap", empleado.id_discap)


def _rubros_rdep(padre: ET.Element, empleado: Empleado) -> None:
    """Rubros anuales en el orden exacto de ``datRetRelDep``.

    Los importes que el XSD marca como obligatorios se envían siempre, aunque
    estén en cero. Los opcionales solo se envían si tienen valor.
    """
    obligatorios = (
        ("suelSal", empleado.suel_sal),
        ("sobSuelComRemu", empleado.sob_suel_com_remu),
        ("partUtil", empleado.part_util),
        ("intGrabGen", empleado.int_grab_gen),
        ("impRentEmpl", empleado.imp_rent_empl),
        ("decimTer", empleado.decim_ter),
        ("decimCuar", empleado.decim_cuar),
        ("fondoReserva", empleado.fondo_reserva),
        ("salarioDigno", empleado.salario_digno),
        ("otrosIngRenGrav", empleado.otros_ing_ren_grav),
        ("ingGravConEsteEmpl", empleado.ing_grav_con_este_empl),
        ("sisSalNet", empleado.sis_sal_net),
        ("apoPerIess", empleado.apo_per_iess),
        ("aporPerIessConOtrosEmpls", empleado.apor_per_iess_con_otros_empls),
        ("deducVivienda", empleado.deduc_vivienda),
        ("deducSalud", empleado.deduc_salud),
    )
    for etiqueta, valor in obligatorios:
        if etiqueta == "sisSalNet":
            _agregar(padre, etiqueta, _entero(valor))
        else:
            _agregar(padre, etiqueta, _importe(valor))

    opcionales = (
        ("deducEduca", empleado.deduc_educa),
        ("deducEducartcult", empleado.deduc_educartcult),
        ("deducAliement", empleado.deduc_aliement),
        ("deducVestim", empleado.deduc_vestim),
        ("deducArtycult", empleado.deduc_artycult),
        ("deduccionTurismo", empleado.deduccion_turismo),
    )
    for etiqueta, valor in opcionales:
        if valor:
            _agregar(padre, etiqueta, _importe(valor))
        elif etiqueta in ("deducEducartcult", "deducAliement", "deducVestim"):
            _agregar(padre, etiqueta, _importe(0))

    obligatorios_finales = (
        ("exoDiscap", empleado.exo_discap),
        ("exoTerEd", empleado.exo_ter_ed),
        ("basImp", empleado.bas_imp),
        ("impRentCaus", empleado.imp_rent_caus),
    )
    for etiqueta, valor in obligatorios_finales:
        _agregar(padre, etiqueta, _importe(valor))

    for etiqueta, valor in (
        ("rebajaGastosPersonales", empleado.rebaja_gastos_personales),
        ("impuestoRentaRebajaGastosPersonales", empleado.impuesto_renta_rebaja_gastos_personales),
    ):
        if valor:
            _agregar(padre, etiqueta, _importe(valor))

    for etiqueta, valor in (
        ("valRetAsuOtrosEmpls", empleado.val_ret_asu_otros_empls),
        ("valImpAsuEsteEmpl", empleado.val_imp_asu_este_empl),
        ("valRet", empleado.val_ret),
    ):
        _agregar(padre, etiqueta, _importe(valor))


def construir_rdep(anio: int) -> ET.Element:
    """Arma el RDEP anual con la estructura del XSD oficial."""
    if not (2000 <= int(anio) <= 9999):
        raise ErrorAnexo("El año del RDEP debe estar entre 2000 y 9999.")
    emisor = _emisor()
    config = _configuracion_rdep()
    root = ET.Element("rdep")
    _agregar(root, "numRuc", _ruc(emisor))
    _agregar(root, "anio", _entero(anio))
    _agregar(root, "tipoEmpleador", config.tipo_empleador)
    _agregar(root, "enteSegSocial", config.ente_seg_social)
    retenciones = ET.SubElement(root, "retRelDep")
    for empleado in Empleado.objects.filter(anio=anio, activo=True).order_by("apellidos", "nombres"):
        detalle = ET.SubElement(retenciones, "datRetRelDep")
        _empleado_rdep(detalle, empleado)
        _rubros_rdep(detalle, empleado)
    return root


def generar_rdep_xml(anio: int) -> bytes:
    """Devuelve el RDEP del año listo para presentar."""
    return _xml(construir_rdep(anio))


# --------------------------------------------------------- registro de apoyo


def generar_csv_compras_ventas(anio: int, mes: int) -> bytes:
    """Registro de compras y ventas en CSV, para revisar y conciliar.

    No sustituye al ATS: es la hoja de trabajo con las mismas bases que se
    informan, para que el contador cuadre antes de presentar.
    """
    _periodo(anio, mes)
    columnas = [
        "TIPO", "COMPROBANTE", "NUMERO", "FECHA", "IDENTIFICACION", "RAZON_SOCIAL",
        "BASE_NO_GRAVADA", "BASE_0", "BASE_GRAVADA", "BASE_EXENTA", "IVA", "TOTAL",
    ]
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(columnas)
    for fila in informes.registro_ventas(anio, mes):
        escritor.writerow(
            [
                "VENTA",
                fila["comprobante"],
                fila["numero"],
                _fecha(fila["fecha"]),
                fila["identificacion"],
                fila["razon_social"],
                "0.00",
                _importe(fila["base_0"]),
                _importe(fila["base_gravada"]),
                _importe(fila["base_exenta"]),
                _importe(fila["iva"]),
                _importe(fila["total"]),
            ]
        )
    for fila in informes.registro_compras(anio, mes):
        escritor.writerow(
            [
                "COMPRA",
                fila["comprobante"],
                fila["numero"],
                _fecha(fila["fecha"]),
                fila["identificacion"],
                fila["razon_social"],
                _importe(fila["base_exenta"]),
                _importe(fila["base_0"]),
                _importe(fila["base_gravada"]),
                "0.00",
                _importe(fila["iva"]),
                _importe(fila["total"]),
            ]
        )
    return salida.getvalue().encode("utf-8-sig")
