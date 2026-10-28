"""Modelos de la contabilidad: el plan de cuentas, los asientos y sus libros.

La contabilidad se lleva por **partida doble**: cada asiento tiene líneas al debe y
al haber que suman lo mismo. De ahí salen los libros (diario y mayor), el balance de
comprobación y los estados financieros.

Todo está pensado para el Ecuador:

* el **plan de cuentas** sigue la estructura de la Superintendencia de Compañías
  (activo, pasivo, patrimonio, ingresos, costos y gastos) y se puede cambiar;
* los **comprobantes del SRI** se contabilizan solos al autorizarse (facturas,
  notas de crédito y de débito, liquidaciones de compra y retenciones);
* las **retenciones** crean la compra del proveedor y su asiento, para que el
  registro de compras y el ATS salgan completos;
* cuando la operación no viene de un comprobante, el asiento se escribe a mano.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from factec.django.documentos import Cliente, Retencion
from factec.django.models import TipoComprobante

__all__ = [
    "AjusteDeLaContabilidad",
    "Asiento",
    "Compra",
    "ConfiguracionContable",
    "Cuenta",
    "Empleado",
    "EstadoAsiento",
    "LineaAsiento",
    "Naturaleza",
    "PeriodoContable",
    "TipoAsiento",
    "TipoCuenta",
]

CERO = Decimal("0.00")


class AjusteDeLaContabilidad(models.Model):
    """Un ajuste de la contabilidad, en la propia tabla del paquete.

    Las claves, los tipos y para qué sirve cada ajuste los declara el paquete (ver
    :mod:`conta_ec.django.ajustes`); al migrar quedan sembrados y desde entonces
    **sólo se cambia el valor**.
    """

    class Tipo(models.TextChoices):
        TEXTO = "texto", "Texto"
        ENTERO = "entero", "Número entero"
        BOOLEANO = "booleano", "Sí o no"
        LISTA = "lista", "Lista separada por comas"

    clave = models.SlugField(
        "clave",
        max_length=60,
        unique=True,
        help_text="Con lo que se lee en el código: contabilidad_periodo_automatico…",
    )
    valor = models.TextField("valor", blank=True)
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices, default=Tipo.TEXTO)
    grupo = models.CharField("grupo", max_length=40, blank=True, default="Contabilidad")
    descripcion = models.CharField(
        "descripción", max_length=220, blank=True, help_text="Para qué es este ajuste."
    )
    orden = models.PositiveIntegerField("orden", default=0)
    editable = models.BooleanField(
        "editable",
        default=True,
        help_text="Los que no lo son sólo los pone el paquete que los declara.",
    )
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "ajuste de la contabilidad"
        verbose_name_plural = "ajustes de la contabilidad"
        ordering = ["grupo", "orden", "clave"]

    def __str__(self) -> str:
        return f"{self.clave} = {self.valor}"

    @property
    def como_valor(self) -> Any:
        """El valor con su tipo: número, sí/no, lista o texto."""
        if self.tipo == self.Tipo.BOOLEANO:
            return str(self.valor).strip().lower() in ("1", "si", "sí", "true", "on", "yes")
        if self.tipo == self.Tipo.ENTERO:
            try:
                return int(str(self.valor).strip())
            except (TypeError, ValueError):
                return 0
        if self.tipo == self.Tipo.LISTA:
            return tuple(
                pieza.strip() for pieza in str(self.valor).split(",") if pieza.strip()
            )
        return self.valor


# ------------------------------------------------------------------ catálogos


class TipoCuenta(models.TextChoices):
    """Los cinco grandes grupos del plan de cuentas ecuatoriano."""

    ACTIVO = "activo", "Activo"
    PASIVO = "pasivo", "Pasivo"
    PATRIMONIO = "patrimonio", "Patrimonio"
    INGRESO = "ingreso", "Ingreso"
    COSTO = "costo", "Costo"
    GASTO = "gasto", "Gasto"


class Naturaleza(models.TextChoices):
    """Si la cuenta crece por el debe o por el haber."""

    DEUDORA = "deudora", "Deudora"
    ACREEDORA = "acreedora", "Acreedora"


class SiNo(models.TextChoices):
    """Respuesta de sí o no, como la pide el SRI."""

    SI = "SI", "Sí"
    NO = "NO", "No"


class TipoEmpleador(models.TextChoices):
    """Tipo de empleador del RDEP (XSD oficial del SRI)."""

    PRIVADO_MIXTO = "PRIVADO_MIXTO", "Privado o mixto"
    PUBLICO = "PUBLICO", "Público"


class EnteSegSocial(models.TextChoices):
    """Ente de seguridad social del RDEP."""

    IESS = "IESS", "IESS"
    ISSFA_ISSPOL = "ISSFA_ISSPOL", "ISSFA / ISSPOL"


class TipoIdentificacionRdep(models.TextChoices):
    """Tipo de documento del empleado en el RDEP (tipIdRet)."""

    CEDULA = "C", "Cédula"
    PASAPORTE = "P", "Pasaporte"
    EXTRANJERO = "E", "Extranjero"


class ResidenciaRdep(models.TextChoices):
    """Código de residencia del trabajador (residenciaTrab)."""

    NO_RESIDENTE = "00", "00 · No residente"
    RESIDENTE = "01", "01 · Residente"
    RESIDENTE_EXTERIOR = "02", "02 · Residente en el exterior"


class AplicaConvenio(models.TextChoices):
    """Convenio de doble imposición (aplicaConvenio)."""

    SI = "SI", "Sí"
    NO = "NO", "No"
    NO_APLICA = "NA", "No aplica"
    SIN_DATO = "SD", "Sin dato"


class TipoDiscapacidad(models.TextChoices):
    """Tipo de trabajador frente a la discapacidad (tipoTrabajDiscap)."""

    NO_APLICA_00 = "00", "00 · No aplica"
    TRABAJADOR = "01", "01 · Trabajador con discapacidad"
    SUSTITUTO = "02", "02 · Sustituto de persona con discapacidad"
    DEPENDIENTE = "03", "03 · Cónyuge, pareja o hijo con discapacidad"
    NO_APLICA_04 = "04", "04 · No aplica"


class TipoIdentificacionDiscapacidad(models.TextChoices):
    """Documento de la persona con discapacidad (tipIdDiscap)."""

    CEDULA = "C", "Cédula"
    PASAPORTE = "P", "Pasaporte"
    EXTRANJERO = "E", "Extranjero"
    NO_APLICA = "N", "No aplica"


class SisSalNet(models.IntegerChoices):
    """Si la retención se calcula por el sistema de salario neto."""

    SIN_SISTEMA = 1, "1 · Sin sistema de salario neto"
    CON_SISTEMA = 2, "2 · Con sistema de salario neto"


#: La naturaleza normal de cada grupo. Las cuentas de corrección (depreciación
#: acumulada, descuentos en ventas…) se crean con la contraria.
NATURALEZA_POR_TIPO = {
    TipoCuenta.ACTIVO.value: Naturaleza.DEUDORA.value,
    TipoCuenta.PASIVO.value: Naturaleza.ACREEDORA.value,
    TipoCuenta.PATRIMONIO.value: Naturaleza.ACREEDORA.value,
    TipoCuenta.INGRESO.value: Naturaleza.ACREEDORA.value,
    TipoCuenta.COSTO.value: Naturaleza.DEUDORA.value,
    TipoCuenta.GASTO.value: Naturaleza.DEUDORA.value,
}


class Cuenta(models.Model):
    """Una cuenta del plan: su código, su nombre y de qué cuenta cuelga.

    Los códigos van por niveles separados por puntos (``1``, ``1.1``,
    ``1.1.01``, ``1.1.01.01``). Una cuenta con hijas no recibe movimientos: los
    asientos se hacen en las cuentas de último nivel, y los totales de las madres
    salen de sumar a las hijas.
    """

    codigo = models.CharField(
        "código", max_length=20, unique=True,
        help_text="Por niveles: 1, 1.1, 1.1.01, 1.1.01.01.",
    )
    nombre = models.CharField("nombre", max_length=200)
    tipo = models.CharField("grupo", max_length=12, choices=TipoCuenta.choices, db_index=True)
    naturaleza = models.CharField(
        "naturaleza", max_length=10, choices=Naturaleza.choices, blank=True,
        help_text="Si se deja vacía se toma la normal del grupo.",
    )
    padre = models.ForeignKey(
        "self", verbose_name="cuenta madre", null=True, blank=True,
        on_delete=models.PROTECT, related_name="hijas",
    )
    nivel = models.PositiveSmallIntegerField("nivel", default=1, editable=False)
    permite_movimientos = models.BooleanField(
        "recibe asientos", default=True,
        help_text="Las cuentas con hijas no reciben asientos: solo suman.",
    )
    activa = models.BooleanField("activa", default=True)
    descripcion = models.TextField("descripción", blank=True)

    creado = models.DateTimeField("creada", auto_now_add=True)
    actualizado = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "cuenta"
        verbose_name_plural = "cuentas"
        ordering = ["codigo"]
        indexes = [models.Index(fields=["tipo", "codigo"], name="conta_ec_tipo_codigo")]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

    # ------------------------------------------------------------ validación

    def clean(self) -> None:
        super().clean()
        padre = self.padre
        if padre is not None:
            if padre.pk == self.pk:
                raise ValidationError({"padre": "Una cuenta no puede ser su propia madre."})
            if padre.tipo != self.tipo:
                raise ValidationError(
                    {"padre": "La cuenta madre tiene que ser del mismo grupo."}
                )
            if not self.codigo.startswith(padre.codigo + "."):
                raise ValidationError(
                    {"codigo": f"El código de una hija de {padre.codigo} empieza por "
                               f"«{padre.codigo}.»."}
                )
        if self.pk and self.hijas.exists() and self.permite_movimientos:
            raise ValidationError(
                {"permite_movimientos": "Esta cuenta tiene hijas: no puede recibir asientos."}
            )
        if self.pk and self.lineas.exists() and self.hijas.exists():
            raise ValidationError(
                {"permite_movimientos": "Una cuenta con movimientos no puede tener hijas."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.nivel = self.codigo.count(".") + 1
        if not self.naturaleza:
            self.naturaleza = NATURALEZA_POR_TIPO.get(self.tipo, Naturaleza.DEUDORA.value)
        if self.padre_id:
            # Una cuenta que tiene hijas no recibe asientos: solo suma.
            Cuenta.objects.filter(pk=self.padre_id, permite_movimientos=True).update(
                permite_movimientos=False
            )
        super().save(*args, **kwargs)

    # --------------------------------------------------------------- ayudas

    @property
    def es_deudora(self) -> bool:
        return self.naturaleza == Naturaleza.DEUDORA.value

    @property
    def es_hoja(self) -> bool:
        """¿Es de último nivel? Solo estas reciben asientos."""
        return not self.hijas.exists()

    def descendientes(self) -> list["Cuenta"]:
        """La cuenta y todas sus hijas, para sumar los saldos."""
        cuentas = [self]
        for hija in self.hijas.all():
            cuentas.extend(hija.descendientes())
        return cuentas

    def saldo_directo(self, desde: Optional[date] = None, hasta: Optional[date] = None) -> Decimal:
        """Lo que tiene la cuenta por sus propios movimientos."""
        consulta = self.lineas.filter(asiento__estado=EstadoAsiento.CONTABILIZADO)
        if desde:
            consulta = consulta.filter(asiento__fecha__gte=desde)
        if hasta:
            consulta = consulta.filter(asiento__fecha__lte=hasta)
        sumas = consulta.aggregate(debe=models.Sum("debe"), haber=models.Sum("haber"))
        return (sumas["debe"] or CERO) - (sumas["haber"] or CERO)

    def saldo(self, desde: Optional[date] = None, hasta: Optional[date] = None) -> Decimal:
        """El saldo con signo natural: positivo si es deudora y debe, etc."""
        saldo = sum(
            (cuenta.saldo_directo(desde=desde, hasta=hasta) for cuenta in self.descendientes()),
            CERO,
        )
        return saldo if self.es_deudora else -saldo

    def saldo_para_balance(self, desde: Optional[date] = None, hasta: Optional[date] = None) -> Decimal:
        """El saldo con el signo de la partida doble (debe − haber)."""
        return sum(
            (cuenta.saldo_directo(desde=desde, hasta=hasta) for cuenta in self.descendientes()),
            CERO,
        )


class PeriodoContable(models.Model):
    """Un mes (o el rango que se quiera) que se abre y se cierra.

    Mientras está abierto se pueden contabilizar asientos con fecha dentro de él.
    Al cerrarlo, ya no entra nada más: es lo que se entrega al contador y a las
    declaraciones del SRI.
    """

    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        CERRADO = "cerrado", "Cerrado"

    nombre = models.CharField("nombre", max_length=60)
    ejercicio = models.PositiveSmallIntegerField("ejercicio")
    mes = models.PositiveSmallIntegerField(
        "mes", null=True, blank=True,
        help_text="1 a 12. Vacío para un periodo que no es mensual.",
    )
    fecha_inicio = models.DateField("desde")
    fecha_fin = models.DateField("hasta")
    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.ABIERTO
    )
    creado = models.DateTimeField("creado", auto_now_add=True)
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "periodo contable"
        verbose_name_plural = "periodos contables"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["fecha_inicio", "fecha_fin"], name="conta_ec_periodo_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.get_estado_display()})"

    def clean(self) -> None:
        super().clean()
        if self.fecha_inicio and self.fecha_fin and self.fecha_inicio > self.fecha_fin:
            raise ValidationError({"fecha_fin": "El periodo no puede terminar antes de empezar."})
        if self.fecha_inicio and self.fecha_fin:
            choque = (
                PeriodoContable.objects.filter(
                    fecha_inicio__lte=self.fecha_fin, fecha_fin__gte=self.fecha_inicio
                )
                .exclude(pk=self.pk)
                .first()
            )
            if choque:
                raise ValidationError(
                    f"Esas fechas se pisan con el periodo «{choque.nombre}»."
                )

    @property
    def abierto(self) -> bool:
        return self.estado == self.Estado.ABIERTO.value

    @classmethod
    def del_mes(cls, anio: int, mes: int) -> Optional["PeriodoContable"]:
        return cls.objects.filter(ejercicio=anio, mes=mes).first()

    @classmethod
    def crear_del_mes(cls, anio: int, mes: int) -> "PeriodoContable":
        """Devuelve el periodo del mes, creándolo si aún no existe."""
        existente = cls.del_mes(anio, mes)
        if existente:
            return existente
        ultimo = calendar.monthrange(anio, mes)[1]
        meses = (
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        )
        nombre = f"{meses[mes - 1].capitalize()} de {anio}"
        return cls.objects.create(
            nombre=nombre,
            ejercicio=anio,
            mes=mes,
            fecha_inicio=date(anio, mes, 1),
            fecha_fin=date(anio, mes, ultimo),
        )


class EstadoAsiento(models.TextChoices):
    BORRADOR = "borrador", "Borrador"
    CONTABILIZADO = "contabilizado", "Contabilizado"
    ANULADO = "anulado", "Anulado"


class TipoAsiento(models.TextChoices):
    DIARIO = "diario", "Diario"
    APERTURA = "apertura", "Apertura"
    AJUSTE = "ajuste", "Ajuste"
    CIERRE = "cierre", "Cierre"
    VENTA = "venta", "Venta"
    COMPRA = "compra", "Compra"
    RETENCION = "retencion", "Retención"


#: De dónde salió el asiento. Se guarda para no contabilizar dos veces lo mismo.
ORIGENES = (
    ("manual", "A mano"),
    ("factura", "Factura"),
    ("nota_credito", "Nota de crédito"),
    ("nota_debito", "Nota de débito"),
    ("liquidacion", "Liquidación de compra"),
    ("retencion", "Retención"),
    ("compra", "Compra"),
    ("cierre", "Cierre del ejercicio"),
)


class Asiento(models.Model):
    """Una partida: lo que se debita y lo que se acredita, con su historia."""

    numero = models.CharField("número", max_length=20, blank=True, db_index=True)
    fecha = models.DateField("fecha")
    concepto = models.CharField("concepto", max_length=300)
    tipo = models.CharField(
        "tipo", max_length=12, choices=TipoAsiento.choices, default=TipoAsiento.DIARIO
    )
    estado = models.CharField(
        "estado", max_length=14, choices=EstadoAsiento.choices,
        default=EstadoAsiento.BORRADOR, db_index=True,
    )
    periodo = models.ForeignKey(
        PeriodoContable, verbose_name="periodo", null=True, blank=True,
        on_delete=models.PROTECT, related_name="asientos",
    )
    referencia = models.CharField(
        "referencia", max_length=120, blank=True,
        help_text="Número de factura, de retención, de compra…",
    )
    comprobante = models.ForeignKey(
        "sri_fe.ComprobanteEmitido", verbose_name="comprobante del SRI",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="asientos_contables",
    )
    origen_tipo = models.CharField(
        "origen", max_length=20, choices=ORIGENES, default="manual", db_index=True
    )
    origen_id = models.PositiveBigIntegerField("id del origen", null=True, blank=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuario", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="asientos_contables",
    )
    motivo_anulacion = models.CharField("motivo de anulación", max_length=300, blank=True)
    creado = models.DateTimeField("creado", auto_now_add=True)
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "asiento"
        verbose_name_plural = "asientos"
        ordering = ["-fecha", "-pk"]
        indexes = [
            models.Index(fields=["fecha", "estado"], name="conta_ec_asiento_fecha"),
            models.Index(fields=["origen_tipo", "origen_id"], name="conta_ec_asiento_origen"),
        ]

    def __str__(self) -> str:
        return f"{self.numero or 'borrador'} · {self.concepto}"

    # ------------------------------------------------------------ validación

    def clean(self) -> None:
        super().clean()
        if self.periodo and self.fecha and not (
            self.periodo.fecha_inicio <= self.fecha <= self.periodo.fecha_fin
        ):
            raise ValidationError(
                {"fecha": f"La fecha no cae dentro del periodo «{self.periodo.nombre}»."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.fecha and self.periodo_id is None:
            from .servicios import periodo_de

            self.periodo = periodo_de(self.fecha)
        super().save(*args, **kwargs)

    # -------------------------------------------------------------- importes

    @property
    def total_debe(self) -> Decimal:
        return self.lineas.aggregate(total=models.Sum("debe"))["total"] or CERO

    @property
    def total_haber(self) -> Decimal:
        return self.lineas.aggregate(total=models.Sum("haber"))["total"] or CERO

    @property
    def diferencia(self) -> Decimal:
        return self.total_debe - self.total_haber

    @property
    def cuadra(self) -> bool:
        return self.diferencia == CERO

    @property
    def editable(self) -> bool:
        return self.estado == EstadoAsiento.BORRADOR.value

    @property
    def contabilizado(self) -> bool:
        return self.estado == EstadoAsiento.CONTABILIZADO.value

    # ------------------------------------------------------------- acciones

    def contabilizar(self, usuario: Any = None) -> "Asiento":
        """Le pone número y lo deja fijo en los libros.

        Comprueba que tenga líneas, que cuadre y que el periodo esté abierto. A
        partir de aquí ya no se edita: si hay que corregirlo, se anula y se hace
        otro.
        """
        if self.estado == EstadoAsiento.CONTABILIZADO.value:
            return self
        if self.estado == EstadoAsiento.ANULADO.value:
            raise ValidationError("Un asiento anulado no se puede contabilizar: haga uno nuevo.")
        if self.periodo is None:
            raise ValidationError("El asiento no tiene periodo.")
        if not self.periodo.abierto:
            raise ValidationError(
                f"El periodo «{self.periodo.nombre}» está cerrado: no admite asientos."
            )

        lineas = list(self.lineas.all())
        if len(lineas) < 2:
            raise ValidationError("Un asiento necesita al menos dos líneas (debe y haber).")
        for linea in lineas:
            linea.validar()
        if self.total_debe != self.total_haber:
            raise ValidationError(
                f"El asiento no cuadra: debe {self.total_debe:.2f} y haber {self.total_haber:.2f}."
            )
        if self.total_debe <= CERO:
            raise ValidationError("Un asiento sin importes no se contabiliza.")

        with transaction.atomic():
            if not self.numero:
                # El periodo se bloquea mientras se numera: dos asientos a la vez
                # (el worker contabilizando facturas y alguien en pantalla) sacaban
                # el mismo correlativo, y el libro diario quedaba con dos
                # «2026-000123».
                PeriodoContable.objects.select_for_update().filter(pk=self.periodo_id).first()
                self.numero = self._siguiente_numero()
            self.estado = EstadoAsiento.CONTABILIZADO.value
            if usuario is not None:
                self.usuario = usuario
            super().save(update_fields=["numero", "estado", "usuario", "actualizado"])
        return self

    def _siguiente_numero(self) -> str:
        """Correlativo por año: 2026-000001."""
        año = self.fecha.year if self.fecha else date.today().year
        ultimo = (
            Asiento.objects.filter(fecha__year=año)
            .exclude(numero="")
            .order_by("-numero")
            .values_list("numero", flat=True)
            .first()
        )
        siguiente = 1
        if ultimo:
            try:
                siguiente = int(ultimo.rsplit("-", 1)[-1]) + 1
            except ValueError:
                siguiente = Asiento.objects.filter(fecha__year=año).count() + 1
        numero = f"{año}-{siguiente:06d}"
        while Asiento.objects.filter(numero=numero).exclude(pk=self.pk).exists():
            siguiente += 1
            numero = f"{año}-{siguiente:06d}"
        return numero

    def anular(self, motivo: str = "", usuario: Any = None) -> "Asiento":
        """Lo saca de los libros.

        No se borra: queda con su historia y su motivo. Los saldos y los informes
        dejan de contarlo.
        """
        if self.estado == EstadoAsiento.ANULADO.value:
            return self
        if self.periodo and not self.periodo.abierto:
            raise ValidationError(
                f"El periodo «{self.periodo.nombre}» está cerrado: no se puede anular."
            )
        self.estado = EstadoAsiento.ANULADO.value
        self.motivo_anulacion = motivo[:300]
        if usuario is not None:
            self.usuario = usuario
        super().save(update_fields=["estado", "motivo_anulacion", "usuario", "actualizado"])
        return self

    @classmethod
    def de_origen(cls, tipo: str, identificador: int) -> Optional["Asiento"]:
        """El asiento que ya se hizo para ese comprobante (si lo hay)."""
        return (
            cls.objects.filter(origen_tipo=tipo, origen_id=identificador)
            .exclude(estado=EstadoAsiento.ANULADO)
            .first()
        )


class LineaAsiento(models.Model):
    """Una línea del asiento: una cuenta, al debe o al haber."""

    asiento = models.ForeignKey(
        Asiento, verbose_name="asiento", on_delete=models.CASCADE, related_name="lineas"
    )
    cuenta = models.ForeignKey(
        Cuenta, verbose_name="cuenta", on_delete=models.PROTECT, related_name="lineas"
    )
    descripcion = models.CharField("detalle", max_length=200, blank=True)
    debe = models.DecimalField("debe", max_digits=18, decimal_places=2, default=CERO)
    haber = models.DecimalField("haber", max_digits=18, decimal_places=2, default=CERO)
    tercero = models.ForeignKey(
        Cliente, verbose_name="tercero", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lineas_contables",
    )
    documento = models.CharField(
        "documento", max_length=30, blank=True,
        help_text="Número del comprobante o documento que respalda la línea.",
    )
    base_impuesto = models.CharField(
        "base de impuesto", max_length=2, blank=True,
        help_text="Código de tarifa del SRI, cuando la línea es una base de IVA.",
    )

    class Meta:
        verbose_name = "línea de asiento"
        verbose_name_plural = "líneas de asiento"
        ordering = ["pk"]

    def __str__(self) -> str:
        return f"{self.cuenta.codigo} · {self.debe or self.haber}"

    def validar(self) -> None:
        """Cada línea va al debe o al haber, nunca a los dos ni a ninguno."""
        if self.debe < CERO or self.haber < CERO:
            raise ValidationError("El debe y el haber no pueden ser negativos.")
        if bool(self.debe) == bool(self.haber):
            raise ValidationError(
                f"La línea «{self.cuenta}» tiene que ir al debe o al haber, no a los dos."
            )
        if not self.cuenta.permite_movimientos:
            raise ValidationError(
                f"La cuenta {self.cuenta.codigo} es de suma: los asientos van en sus hijas."
            )
        if self.cuenta.hijas.exists():
            raise ValidationError(
                f"La cuenta {self.cuenta.codigo} tiene hijas: use una cuenta de último nivel."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.debe = self.debe or CERO
        self.haber = self.haber or CERO
        super().save(*args, **kwargs)


class ConfiguracionContable(models.Model):
    """Qué cuenta se usa para cada cosa que se contabiliza sola.

    Se llena una vez, desde «Configuración contable». Sin ella, los comprobantes se
    pueden seguir emitiendo, pero no se contabilizan automáticamente.
    """

    nombre = models.CharField("nombre", max_length=80, default="Contabilidad principal")
    activa = models.BooleanField("activa", default=True)

    cuenta_caja = models.ForeignKey(
        Cuenta, verbose_name="caja", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_banco = models.ForeignKey(
        Cuenta, verbose_name="bancos", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_clientes = models.ForeignKey(
        Cuenta, verbose_name="cuentas por cobrar clientes", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_proveedores = models.ForeignKey(
        Cuenta, verbose_name="cuentas por pagar proveedores", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_iva_ventas = models.ForeignKey(
        Cuenta, verbose_name="IVA por pagar (ventas)", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_iva_compras = models.ForeignKey(
        Cuenta, verbose_name="IVA crédito tributario (compras)", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_ventas_bienes = models.ForeignKey(
        Cuenta, verbose_name="ventas de bienes", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_ventas_servicios = models.ForeignKey(
        Cuenta, verbose_name="prestación de servicios", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_otros_ingresos = models.ForeignKey(
        Cuenta, verbose_name="otros ingresos", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_descuentos_ventas = models.ForeignKey(
        Cuenta, verbose_name="descuentos y devoluciones en ventas", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_inventario = models.ForeignKey(
        Cuenta, verbose_name="inventario", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_compras_gastos = models.ForeignKey(
        Cuenta, verbose_name="compras y gastos por defecto", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
        help_text="Se usa cuando la compra no dice a qué cuenta va.",
    )
    cuenta_costo_ventas = models.ForeignKey(
        Cuenta, verbose_name="costo de ventas", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_retencion_renta_por_pagar = models.ForeignKey(
        Cuenta, verbose_name="retenciones de renta por pagar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_retencion_iva_por_pagar = models.ForeignKey(
        Cuenta, verbose_name="retenciones de IVA por pagar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_retencion_isd_por_pagar = models.ForeignKey(
        Cuenta, verbose_name="retenciones de ISD por pagar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_retencion_renta_por_cobrar = models.ForeignKey(
        Cuenta, verbose_name="retenciones de renta por cobrar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_retencion_iva_por_cobrar = models.ForeignKey(
        Cuenta, verbose_name="retenciones de IVA por cobrar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_resultado_ejercicio = models.ForeignKey(
        Cuenta, verbose_name="resultado del ejercicio", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_resultados_acumulados = models.ForeignKey(
        Cuenta, verbose_name="resultados acumulados", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_reserva_legal = models.ForeignKey(
        Cuenta, verbose_name="reserva legal", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_impuesto_renta = models.ForeignKey(
        Cuenta, verbose_name="gasto por impuesto a la renta", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    cuenta_iess_por_pagar = models.ForeignKey(
        Cuenta, verbose_name="IESS por pagar", null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )

    # --- datos que pide el anexo RDEP, no la contabilidad ---
    tipo_empleador = models.CharField(
        "tipo de empleador (RDEP)", max_length=15, choices=TipoEmpleador.choices,
        default=TipoEmpleador.PRIVADO_MIXTO.value,
    )
    ente_seg_social = models.CharField(
        "ente de seguridad social (RDEP)", max_length=15, choices=EnteSegSocial.choices,
        default=EnteSegSocial.IESS.value,
    )

    creado = models.DateTimeField("creada", auto_now_add=True)
    actualizado = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "configuración contable"
        verbose_name_plural = "configuraciones contables"

    def __str__(self) -> str:
        return self.nombre

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Solo puede haber una configuración activa a la vez."""
        if self.activa:
            ConfiguracionContable.objects.exclude(pk=self.pk).update(activa=False)
        super().save(*args, **kwargs)

    @classmethod
    def activa_actual(cls) -> Optional["ConfiguracionContable"]:
        return cls.objects.filter(activa=True).order_by("-pk").first()

    def faltantes(self) -> list[str]:
        """Las cuentas obligatorias que todavía no se han elegido."""
        obligatorias = {
            "cuenta_clientes": "cuentas por cobrar clientes",
            "cuenta_proveedores": "cuentas por pagar proveedores",
            "cuenta_iva_ventas": "IVA por pagar",
            "cuenta_iva_compras": "IVA crédito tributario",
            "cuenta_ventas_bienes": "ventas de bienes",
            "cuenta_ventas_servicios": "prestación de servicios",
            "cuenta_compras_gastos": "compras y gastos",
            "cuenta_retencion_renta_por_pagar": "retenciones de renta por pagar",
            "cuenta_retencion_iva_por_pagar": "retenciones de IVA por pagar",
        }
        return [texto for campo, texto in obligatorias.items() if not getattr(self, campo)]


class Compra(models.Model):
    """La factura (o liquidación) de un proveedor, registrada para contabilizar.

    Las retenciones que se emiten al proveedor crean esta compra sola: el documento
    sustento ya trae la base, el IVA y el total. También se puede escribir a mano
    cuando no se emitió retención.

    De aquí salen el asiento de compra, el registro de compras y el ATS.
    """

    proveedor = models.ForeignKey(
        Cliente, verbose_name="proveedor", on_delete=models.PROTECT, related_name="compras"
    )
    tipo_comprobante = models.CharField(
        "tipo de comprobante", max_length=3, choices=TipoComprobante.choices,
        default=TipoComprobante.FACTURA.value,
    )
    cod_sustento = models.CharField(
        "código de sustento", max_length=2, default="01",
        help_text=(
            "Tabla 5 del SRI. Con 01 el IVA va al crédito tributario; con 02, 03 o "
            "sin derecho a crédito, el IVA forma parte del costo o gasto."
        ),
    )
    numero = models.CharField("número", max_length=15, help_text="15 dígitos, sin guiones.")
    autorizacion = models.CharField("autorización", max_length=49, blank=True)
    fecha = models.DateField("fecha de emisión")
    concepto = models.CharField("concepto", max_length=300)
    forma_pago = models.CharField("forma de pago", max_length=2, default="01")

    base_no_grava = models.DecimalField(
        "base no gravada (no objeto)", max_digits=14, decimal_places=2, default=CERO
    )
    base_exenta = models.DecimalField(
        "base exenta de IVA", max_digits=14, decimal_places=2, default=CERO
    )
    base_iva_0 = models.DecimalField(
        "base IVA 0 %", max_digits=14, decimal_places=2, default=CERO
    )
    base_iva = models.DecimalField(
        "base IVA gravada", max_digits=14, decimal_places=2, default=CERO
    )
    valor_iva = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=CERO)
    propina = models.DecimalField(
        "propina", max_digits=14, decimal_places=2, default=CERO
    )
    total = models.DecimalField("total", max_digits=14, decimal_places=2, default=CERO)

    cuenta = models.ForeignKey(
        Cuenta, verbose_name="cuenta de compra o gasto", null=True, blank=True,
        on_delete=models.PROTECT, related_name="compras",
        help_text="Inventario, costo o gasto al que va la compra.",
    )
    retencion = models.ForeignKey(
        Retencion, verbose_name="retención", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compras",
    )
    asiento = models.OneToOneField(
        Asiento, verbose_name="asiento", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compra",
    )
    periodo = models.ForeignKey(
        PeriodoContable, verbose_name="periodo", null=True, blank=True,
        on_delete=models.PROTECT, related_name="compras",
    )
    creado = models.DateTimeField("creada", auto_now_add=True)
    actualizado = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "compra"
        verbose_name_plural = "compras"
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["proveedor", "tipo_comprobante", "numero"],
                name="conta_ec_compra_unica",
            )
        ]
        indexes = [models.Index(fields=["fecha"], name="conta_ec_compra_fecha")]

    def __str__(self) -> str:
        return f"{self.get_tipo_comprobante_display()} {self.numero} · {self.proveedor}"

    @property
    def numero_con_guiones(self) -> str:
        limpio = "".join(c for c in self.numero if c.isdigit())
        if len(limpio) != 15:
            return limpio
        return f"{limpio[:3]}-{limpio[3:6]}-{limpio[6:]}"

    @property
    def subtotal(self) -> Decimal:
        return self.base_no_grava + self.base_exenta + self.base_iva_0 + self.base_iva

    @property
    def total_retenido(self) -> Decimal:
        return self.retencion.total_retenido if self.retencion_id else CERO

    @property
    def saldo_por_pagar(self) -> Decimal:
        return self.total - self.total_retenido

    def clean(self) -> None:
        super().clean()
        self.numero = "".join(c for c in (self.numero or "") if c.isdigit())
        if self.numero and len(self.numero) != 15:
            raise ValidationError({"numero": "El número del comprobante debe tener 15 dígitos."})
        for campo in (
            "base_no_grava", "base_exenta", "base_iva_0", "base_iva",
            "valor_iva", "propina", "total",
        ):
            if (getattr(self, campo) or CERO) < CERO:
                raise ValidationError({campo: "El importe no puede ser negativo."})
        esperado = self.subtotal + self.valor_iva + self.propina
        if self.total and abs(self.total - esperado) > Decimal("0.01"):
            raise ValidationError(
                {"total": f"El total no cuadra: bases + IVA + propina dan {esperado:.2f}."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.numero = "".join(c for c in (self.numero or "") if c.isdigit())
        if not self.total:
            self.total = self.subtotal + self.valor_iva + self.propina
        if self.fecha and self.periodo_id is None:
            from .servicios import periodo_de

            self.periodo = periodo_de(self.fecha)
        super().save(*args, **kwargs)


def _importe_rdep(verbose_name: str) -> models.DecimalField:
    """Un importe anual del RDEP: catorce enteros y dos decimales."""
    return models.DecimalField(
        verbose_name, max_digits=14, decimal_places=2, default=CERO
    )


class Empleado(models.Model):
    """Ficha anual de un empleado para el RDEP, con los campos del XSD del SRI.

    No es una nómina: el SRI pide, por cada trabajador y año, los rubros que
    forman su ingreso gravado, los aportes y la retención. Los nombres de los
    campos siguen el esquema oficial (``suelSal``, ``apoPerIess``…) para que no
    haya dudas al generar el XML.

    Base: artículo 43 de la LORTI y Resolución NAC-DGERCGC24-00000002, que
    actualiza el anexo de retenciones en la fuente bajo relación de dependencia.
    """

    anio = models.PositiveSmallIntegerField("año")
    tipo_identificacion = models.CharField(
        "tipo de identificación (tipIdRet)", max_length=1,
        choices=TipoIdentificacionRdep.choices, default=TipoIdentificacionRdep.CEDULA.value,
    )
    identificacion = models.CharField("identificación (idRet)", max_length=13)
    apellidos = models.CharField("apellidos (apellidoTrab)", max_length=100)
    nombres = models.CharField("nombres (nombreTrab)", max_length=100)
    establecimiento = models.CharField("establecimiento (estab)", max_length=3, default="001")

    residencia = models.CharField(
        "residencia (residenciaTrab)", max_length=2, choices=ResidenciaRdep.choices,
        default=ResidenciaRdep.RESIDENTE.value,
    )
    pais_residencia = models.CharField(
        "país de residencia (paisResidencia)", max_length=3, default="593",
        help_text="Código de país del SRI. Ecuador es 593.",
    )
    aplica_convenio = models.CharField(
        "aplica convenio (aplicaConvenio)", max_length=2, choices=AplicaConvenio.choices,
        default=AplicaConvenio.NO.value,
    )
    ben_galpg = models.CharField(
        "beneficiario de gastos personales (benGalpg)", max_length=2,
        choices=SiNo.choices, default=SiNo.NO.value,
    )
    enf_catastro = models.CharField(
        "enfermedad catastrófica (enfcatastro)", max_length=2,
        choices=SiNo.choices, default=SiNo.NO.value, blank=True,
    )
    num_carg_reb_gast_pers = models.PositiveSmallIntegerField(
        "cargas para rebaja de gastos personales", default=0,
        help_text="De 0 a 5.",
    )
    tipo_trabaj_discap = models.CharField(
        "tipo de trabajador con discapacidad (tipoTrabajDiscap)", max_length=2,
        choices=TipoDiscapacidad.choices, default=TipoDiscapacidad.NO_APLICA_04.value,
    )
    porcentaje_discap = models.PositiveSmallIntegerField(
        "porcentaje de discapacidad", default=0
    )
    tip_id_discap = models.CharField(
        "tipo de documento de la persona con discapacidad", max_length=1,
        choices=TipoIdentificacionDiscapacidad.choices,
        default=TipoIdentificacionDiscapacidad.NO_APLICA.value,
    )
    id_discap = models.CharField(
        "identificación de la persona con discapacidad", max_length=13, blank=True
    )
    sis_sal_net = models.PositiveSmallIntegerField(
        "sistema de salario neto (sisSalNet)", choices=SisSalNet.choices,
        default=SisSalNet.SIN_SISTEMA.value,
    )

    # --- rubros del año (datRetRelDep) ---
    suel_sal = _importe_rdep("sueldos y salarios (suelSal)")
    sob_suel_com_remu = _importe_rdep("sobresueldos y comisiones (sobSuelComRemu)")
    part_util = _importe_rdep("participación de utilidades (partUtil)")
    int_grab_gen = _importe_rdep("intereses gravados (intGrabGen)")
    imp_rent_empl = _importe_rdep("impuesto a la renta asumido por el empleador (impRentEmpl)")
    decim_ter = _importe_rdep("décimo tercero (decimTer)")
    decim_cuar = _importe_rdep("décimo cuarto (decimCuar)")
    fondo_reserva = _importe_rdep("fondo de reserva (fondoReserva)")
    salario_digno = _importe_rdep("salario digno (salarioDigno)")
    otros_ing_ren_grav = _importe_rdep("otros ingresos gravados (otrosIngRenGrav)")
    ing_grav_con_este_empl = _importe_rdep("ingreso gravado con este empleador (ingGravConEsteEmpl)")
    apo_per_iess = _importe_rdep("aporte personal al IESS (apoPerIess)")
    apor_per_iess_con_otros_empls = _importe_rdep(
        "aportes personales con otros empleadores (aporPerIessConOtrosEmpls)"
    )
    deduc_vivienda = _importe_rdep("deducción por vivienda (deducVivienda)")
    deduc_salud = _importe_rdep("deducción por salud (deducSalud)")
    deduc_educa = _importe_rdep("deducción por educación (deducEduca)")
    deduc_educartcult = _importe_rdep("deducción por educación, arte y cultura (deducEducartcult)")
    deduc_aliement = _importe_rdep("deducción por alimentación (deducAliement)")
    deduc_vestim = _importe_rdep("deducción por vestimenta (deducVestim)")
    deduc_artycult = _importe_rdep("deducción por arte y cultura (deducArtycult)")
    deduccion_turismo = _importe_rdep("deducción por turismo (deduccionTurismo)")
    exo_discap = _importe_rdep("exoneración por discapacidad (exoDiscap)")
    exo_ter_ed = _importe_rdep("exoneración por tercera edad (exoTerEd)")
    bas_imp = _importe_rdep("base imponible (basImp)")
    imp_rent_caus = _importe_rdep("impuesto a la renta causado (impRentCaus)")
    rebaja_gastos_personales = _importe_rdep(
        "rebaja por gastos personales (rebajaGastosPersonales)"
    )
    impuesto_renta_rebaja_gastos_personales = _importe_rdep(
        "impuesto a la renta con rebaja de gastos personales"
    )
    val_ret_asu_otros_empls = _importe_rdep(
        "retención asumida con otros empleadores (valRetAsuOtrosEmpls)"
    )
    val_imp_asu_este_empl = _importe_rdep(
        "impuesto asumido con este empleador (valImpAsuEsteEmpl)"
    )
    val_ret = _importe_rdep("retención en la fuente (valRet)")

    activo = models.BooleanField("activo", default=True)
    creado = models.DateTimeField("creado", auto_now_add=True)
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "empleado (RDEP)"
        verbose_name_plural = "empleados (RDEP)"
        ordering = ["apellidos", "nombres"]
        constraints = [
            models.UniqueConstraint(
                fields=["anio", "identificacion"], name="conta_ec_empleado_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.apellidos} {self.nombres} ({self.anio})"

    @property
    def nombre_completo(self) -> str:
        return f"{self.apellidos} {self.nombres}".strip()

    def clean(self) -> None:
        super().clean()
        self.identificacion = "".join(
            c for c in (self.identificacion or "") if c.isalnum()
        )
        if self.identificacion and not (3 <= len(self.identificacion) <= 13):
            raise ValidationError(
                {"identificacion": "La identificación debe tener entre 3 y 13 caracteres."}
            )
        for campo in ("apellidos", "nombres"):
            valor = getattr(self, campo) or ""
            if not (2 <= len(valor) <= 100):
                raise ValidationError({campo: "Escriba entre 2 y 100 caracteres."})
        if self.establecimiento and not (len(self.establecimiento) == 3 and self.establecimiento.isdigit()):
            raise ValidationError({"establecimiento": "El establecimiento son tres dígitos."})
        if self.pais_residencia and not (len(self.pais_residencia) == 3 and self.pais_residencia.isdigit()):
            raise ValidationError({"pais_residencia": "El país es un código de tres dígitos."})
        if not (0 <= self.num_carg_reb_gast_pers <= 5):
            raise ValidationError({"num_carg_reb_gast_pers": "Las cargas van de 0 a 5."})
        if not (0 <= self.porcentaje_discap <= 100):
            raise ValidationError({"porcentaje_discap": "El porcentaje va de 0 a 100."})
        for campo in self._meta.fields:
            if isinstance(campo, models.DecimalField):
                if (getattr(self, campo.name) or CERO) < CERO:
                    raise ValidationError({campo.name: "El importe no puede ser negativo."})
