"""Pruebas de la contabilidad y de los anexos del SRI."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase
from factec.django.documentos import (
    Cliente,
    Factura,
    Producto,
    Retencion,
)
from factec.django.models import (
    ComprobanteEmitido,
    ConfiguracionEmisor,
    EstadoComprobante,
)

from . import anexos, informes, servicios
from .models import (
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    Empleado,
    EstadoAsiento,
    LineaAsiento,
    PeriodoContable,
    TipoAsiento,
)


class BaseContabilidad(TestCase):
    """Datos mínimos: emisor, cliente, producto y cuentas sembradas."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.emisor = ConfiguracionEmisor.objects.create(
            nombre="Prueba",
            activo=True,
            ruc="1790012345001",
            razon_social="EMPRESA DE PRUEBA",
            dir_matriz="Quito",
            estab="001",
            pto_emi="001",
        )
        cls.cliente = Cliente.objects.create(
            razon_social="CLIENTE DE PRUEBA",
            identificacion="1712345678001",
            tipo_identificacion="04",
        )
        cls.proveedor = Cliente.objects.create(
            razon_social="PROVEEDOR DE PRUEBA",
            identificacion="1790012344001",
            tipo_identificacion="04",
        )
        cls.producto = Producto.objects.create(
            codigo_principal="P001",
            descripcion="Producto de prueba",
            precio_unitario=Decimal("100.00"),
            codigo_porcentaje_iva="4",
        )

    def factura(self, *, clave: str, numero: str = "000000001") -> Factura:
        factura = Factura.objects.create(
            receptor=self.cliente,
            fecha_emision=date(2031, 3, 15),
            forma_pago="01",
        )
        factura.detalles.create(
            producto=self.producto,
            cantidad=Decimal("2"),
            precio_unitario=Decimal("100.00"),
            codigo_porcentaje_iva="4",
        )
        comprobante = ComprobanteEmitido.objects.create(
            configuracion=self.emisor,
            content_type=ContentType.objects.get_for_model(Factura),
            object_id=factura.pk,
            clave_acceso=clave,
            tipo_comprobante="01",
            secuencial=numero,
            fecha_emision=factura.fecha_emision,
            razon_social_receptor=self.cliente.razon_social,
            identificacion_receptor=self.cliente.identificacion,
            importe_total=factura.total,
            estado=EstadoComprobante.AUTORIZADO.value,
            numero_autorizacion="9" * 49,
        )
        factura.comprobante = comprobante
        factura.save(update_fields=["comprobante", "actualizado"])
        factura.refresh_from_db()
        return factura

    def retencion(self, *, clave: str) -> Retencion:
        retencion = Retencion.objects.create(
            sujeto_retenido=self.proveedor,
            fecha_emision=date(2031, 3, 20),
            periodo_fiscal=date(2031, 3, 1),
            tipo_sujeto_retenido="01",
        )
        documento = retencion.docs_sustento.create(
            cod_sustento="01",
            cod_doc_sustento="01",
            num_doc_sustento="001001000000999",
            fecha_emision=date(2031, 3, 18),
            num_aut_doc_sustento="8" * 49,
            total_sin_impuestos=Decimal("100.00"),
            importe_total=Decimal("115.00"),
        )
        documento.impuestos.create(
            codigo="2",
            codigo_porcentaje="4",
            base_imponible=Decimal("100.00"),
            tarifa=Decimal("15.00"),
            valor=Decimal("15.00"),
        )
        documento.retenciones.create(
            codigo="1",
            codigo_retencion="312",
            base_imponible=Decimal("100.00"),
            porcentaje_retener=Decimal("1.00"),
            valor_retenido=Decimal("1.00"),
        )
        documento.retenciones.create(
            codigo="2",
            codigo_retencion="9",
            base_imponible=Decimal("15.00"),
            porcentaje_retener=Decimal("10.00"),
            valor_retenido=Decimal("1.50"),
        )
        comprobante = ComprobanteEmitido.objects.create(
            configuracion=self.emisor,
            content_type=ContentType.objects.get_for_model(Retencion),
            object_id=retencion.pk,
            clave_acceso=clave,
            tipo_comprobante="07",
            secuencial="000000001",
            fecha_emision=retencion.fecha_emision,
            razon_social_receptor=self.proveedor.razon_social,
            identificacion_receptor=self.proveedor.identificacion,
            importe_total=Decimal("2.50"),
            estado=EstadoComprobante.AUTORIZADO.value,
            numero_autorizacion="7" * 49,
        )
        retencion.comprobante = comprobante
        retencion.save(update_fields=["comprobante", "actualizado"])
        retencion.refresh_from_db()
        return retencion


class PruebasDelPlan(BaseContabilidad):
    def test_plan_sembrado_y_configurado(self) -> None:
        self.assertGreaterEqual(Cuenta.objects.count(), 100)
        caja = Cuenta.objects.get(codigo="1.1.01.01")
        activo = Cuenta.objects.get(codigo="1.1.01")
        self.assertTrue(caja.permite_movimientos)
        self.assertFalse(activo.permite_movimientos)
        config = ConfiguracionContable.activa_actual()
        self.assertIsNotNone(config)
        self.assertEqual(config.faltantes(), [])

    def test_una_cuenta_madre_no_recibe_asientos(self) -> None:
        activo = Cuenta.objects.get(codigo="1.1.01")
        with self.assertRaises(ValidationError):
            LineaAsiento(
                asiento=Asiento(fecha=date(2031, 3, 1), concepto="x"),
                cuenta=activo,
                debe=Decimal("10"),
            ).validar()


class PruebasDeAsientos(BaseContabilidad):
    def test_el_asiento_tiene_que_cuadrar(self) -> None:
        asiento = Asiento.objects.create(
            fecha=date(2031, 3, 1),
            concepto="Asiento descuadrado",
        )
        cuenta = Cuenta.objects.get(codigo="1.1.01.01")
        otra = Cuenta.objects.get(codigo="4.1.01")
        LineaAsiento.objects.create(asiento=asiento, cuenta=cuenta, debe=Decimal("10"))
        LineaAsiento.objects.create(asiento=asiento, cuenta=otra, haber=Decimal("9"))
        with self.assertRaises(ValidationError):
            asiento.contabilizar()

    def test_asiento_manual_cuadrado(self) -> None:
        caja = Cuenta.objects.get(codigo="1.1.01.01")
        ventas = Cuenta.objects.get(codigo="4.1.01")
        asiento = servicios.crear_asiento(
            fecha=date(2031, 3, 1),
            concepto="Aporte en efectivo",
            lineas=[
                {"cuenta": caja, "debe": Decimal("100.00")},
                {"cuenta": ventas, "haber": Decimal("100.00")},
            ],
        )
        self.assertIsNotNone(asiento)
        self.assertEqual(asiento.estado, EstadoAsiento.CONTABILIZADO.value)
        self.assertEqual(asiento.total_debe, Decimal("100.00"))
        self.assertTrue(asiento.cuadra)


class PruebasDeContabilizacionAutomatica(BaseContabilidad):
    def test_factura_autorizada_se_contabiliza_sola(self) -> None:
        factura = self.factura(clave="1" * 49)
        asiento = Asiento.objects.get(origen_tipo="factura", origen_id=factura.pk)
        self.assertEqual(asiento.estado, EstadoAsiento.CONTABILIZADO.value)
        lineas = {linea.cuenta.codigo: linea for linea in asiento.lineas.select_related("cuenta")}
        self.assertEqual(lineas["1.1.02.01"].debe, Decimal("230.00"))
        self.assertEqual(lineas["4.1.01"].haber, Decimal("200.00"))
        self.assertEqual(lineas["2.1.05.01"].haber, Decimal("30.00"))
        self.assertTrue(asiento.cuadra)

    def test_retencion_crea_compra_y_dos_asientos(self) -> None:
        retencion = self.retencion(clave="2" * 49)
        compra = Compra.objects.get(numero="001001000000999")
        self.assertEqual(compra.total, Decimal("115.00"))
        self.assertEqual(compra.retencion_id, retencion.pk)
        self.assertIsNotNone(compra.asiento_id)
        asiento_retencion = Asiento.objects.get(origen_tipo="retencion", origen_id=retencion.pk)
        self.assertTrue(asiento_retencion.cuadra)
        self.assertEqual(asiento_retencion.total_debe, Decimal("2.50"))

    def test_no_se_contabiliza_dos_veces(self) -> None:
        factura = self.factura(clave="3" * 49)
        antes = Asiento.objects.count()
        servicios.contabilizar_factura(factura, comprobante=factura.comprobante)
        self.assertEqual(Asiento.objects.count(), antes)

    def test_sustento_02_no_usa_credito_tributario(self) -> None:
        compra = Compra.objects.create(
            proveedor=self.proveedor,
            tipo_comprobante="01",
            cod_sustento="02",
            numero="001001000000888",
            autorizacion="5" * 49,
            fecha=date(2031, 4, 10),
            concepto="Compra sin derecho a crédito",
            base_iva=Decimal("100.00"),
            valor_iva=Decimal("15.00"),
            total=Decimal("115.00"),
            cuenta=Cuenta.objects.get(codigo="5.3.11"),
        )
        asiento = servicios.contabilizar_compra(compra)
        self.assertIsNotNone(asiento)
        cuentas = {linea.cuenta.codigo: linea for linea in asiento.lineas.select_related("cuenta")}
        self.assertNotIn("1.1.04.01", cuentas)
        self.assertEqual(cuentas["5.3.11"].debe, Decimal("115.00"))


class PruebasDeInformes(BaseContabilidad):
    def test_balance_y_resultado(self) -> None:
        self.factura(clave="4" * 49)
        balance = informes.balance_comprobacion(date(2031, 3, 1), date(2031, 3, 31))
        self.assertGreater(balance["total_debe"], Decimal("0"))
        resultado = informes.estado_resultados(date(2031, 3, 1), date(2031, 3, 31))
        self.assertEqual(resultado["total_ingresos"], Decimal("200.00"))
        self.assertEqual(resultado["resultado"], Decimal("200.00"))

    def test_cierre_del_ejercicio(self) -> None:
        self.factura(clave="5" * 49)
        caja = Cuenta.objects.get(codigo="1.1.01.01")
        gasto = Cuenta.objects.get(codigo="5.3.11")
        servicios.crear_asiento(
            fecha=date(2031, 6, 1),
            concepto="Gasto de prueba",
            lineas=[
                {"cuenta": gasto, "debe": Decimal("50.00")},
                {"cuenta": caja, "haber": Decimal("50.00")},
            ],
        )
        cierre = servicios.cerrar_ejercicio(2031)
        self.assertIsNotNone(cierre)
        self.assertTrue(cierre.cuadra)
        self.assertTrue(
            PeriodoContable.objects.filter(ejercicio=2031).exclude(
                estado=PeriodoContable.Estado.CERRADO.value
            ).count() == 0
        )
        # El periodo ya cerrado no admite otro asiento.
        with self.assertRaises(ValidationError):
            servicios.crear_asiento(
                fecha=date(2031, 7, 1),
                concepto="Después del cierre",
                lineas=[
                    {"cuenta": caja, "debe": Decimal("1.00")},
                    {"cuenta": gasto, "haber": Decimal("1.00")},
                ],
            )


class PruebasDeAnexos(BaseContabilidad):
    def test_ats_respeta_el_esquema_oficial(self) -> None:
        self.factura(clave="6" * 49)
        contenido = anexos.generar_ats_xml(2031, 3)
        root = ET.fromstring(contenido)
        self.assertEqual(root.tag, "iva")
        self.assertEqual(
            [hijo.tag for hijo in root][:11],
            [
                "TipoIDInformante", "IdInformante", "razonSocial", "Anio", "Mes",
                "numEstabRuc", "totalVentas", "codigoOperativo", "compras",
                "ventas", "ventasEstablecimiento",
            ],
        )
        self.assertEqual(root.findtext("IdInformante"), "1790012345001")
        self.assertEqual(root.findtext("Anio"), "2031")
        self.assertEqual(root.findtext("Mes"), "03")
        venta = root.find("ventas/detalleVentas")
        self.assertIsNotNone(venta)
        self.assertEqual(
            [hijo.tag for hijo in venta][:10],
            [
                "tpIdCliente", "idCliente", "parteRelVtas", "tipoComprobante",
                "tipoEmision", "numeroComprobantes", "baseNoGraIva",
                "baseImponible", "baseImpGrav", "montoIva",
            ],
        )
        self.assertEqual(venta.findtext("numeroComprobantes"), "1")
        self.assertEqual(venta.findtext("baseImpGrav"), "200.00")
        self.assertEqual(venta.findtext("montoIva"), "30.00")
        self.assertEqual(root.findtext("totalVentas"), "230.00")

    def test_ats_de_compra_y_retencion(self) -> None:
        self.retencion(clave="7" * 49)
        root = ET.fromstring(anexos.generar_ats_xml(2031, 3))
        compra = root.find("compras/detalleCompras")
        self.assertIsNotNone(compra)
        self.assertEqual(compra.findtext("codSustento"), "01")
        self.assertRegex(
            compra.findtext("fechaEmision") or "", r"^\d{2}/\d{2}/\d{4}$"
        )
        self.assertEqual(compra.findtext("baseImpGrav"), "100.00")
        self.assertEqual(compra.findtext("montoIva"), "15.00")
        self.assertEqual(compra.findtext("valRetBien10"), "1.50")
        self.assertEqual(compra.findtext("formasDePago/formaPago"), "01")

    def test_reoc_lleva_la_retencion_de_renta(self) -> None:
        self.retencion(clave="8" * 49)
        root = ET.fromstring(anexos.generar_reoc_xml(2031, 3))
        self.assertEqual(root.tag, "reoc")
        self.assertEqual(
            [hijo.tag for hijo in root],
            ["numeroRuc", "anio", "mes", "compras"],
        )
        detalle = root.find("compras/detalleCompras")
        self.assertIsNotNone(detalle)
        self.assertEqual(detalle.findtext("tipoComp"), "01")
        retencion = detalle.find("air/detalleAir")
        self.assertIsNotNone(retencion)
        self.assertEqual(retencion.findtext("codRetAir"), "312")
        self.assertEqual(retencion.findtext("valRetAir"), "1.00")

    def test_registro_de_compras_y_ventas_en_csv(self) -> None:
        self.factura(clave="9" * 49)
        contenido = anexos.generar_csv_compras_ventas(2031, 3)
        texto = contenido.decode("utf-8-sig")
        self.assertIn("TIPO;COMPROBANTE;NUMERO", texto)
        self.assertIn("VENTA;Factura", texto)

    def test_rdep_respeta_el_esquema(self) -> None:
        Empleado.objects.create(
            anio=2031,
            tipo_identificacion="C",
            identificacion="1712345678",
            apellidos="Pérez",
            nombres="José",
            establecimiento="001",
            residencia="01",
            pais_residencia="593",
            aplica_convenio="NO",
            ben_galpg="NO",
            tipo_trabaj_discap="04",
            tip_id_discap="N",
            suel_sal=Decimal("12000.00"),
            apo_per_iess=Decimal("1125.00"),
        )
        root = ET.fromstring(anexos.generar_rdep_xml(2031))
        self.assertEqual(root.tag, "rdep")
        self.assertEqual(
            [hijo.tag for hijo in root],
            ["numRuc", "anio", "tipoEmpleador", "enteSegSocial", "retRelDep"],
        )
        empleado = root.find("retRelDep/datRetRelDep/empleado")
        self.assertIsNotNone(empleado)
        self.assertEqual(
            [hijo.tag for hijo in empleado][:6],
            ["benGalpg", "enfcatastro", "tipIdRet", "idRet", "apellidoTrab", "nombreTrab"],
        )
        self.assertEqual(empleado.findtext("apellidoTrab"), "Perez")
        self.assertEqual(empleado.findtext("nombreTrab"), "Jose")
        datos = root.find("retRelDep/datRetRelDep")
        self.assertEqual(datos.findtext("suelSal"), "12000.00")
        self.assertEqual(datos.findtext("sisSalNet"), "1")
        self.assertEqual(datos.findtext("valRet"), "0.00")
