"""Formularios de la contabilidad: cuentas, asientos, compras y RDEP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from factec.django.documentos import Cliente
from factec.django.models import TipoComprobante
from factec.sri.fechas import hoy_en_ecuador

from .ui import campos as _campos_del_proyecto

_campos = _campos_del_proyecto()
CampoImporte = _campos.CampoImporte
caja = _campos.caja
desplegable = _campos.desplegable
fecha = _campos.fecha
numero = _campos.numero

from .models import (
    CERO,
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    Empleado,
    LineaAsiento,
    PeriodoContable,
    TipoAsiento,
)

__all__ = [
    "AsientoForm",
    "CompraForm",
    "ConfiguracionContableForm",
    "CuentaForm",
    "EmpleadoForm",
    "LineaAsientoForm",
    "PeriodoForm",
    "formset_de_lineas",
]


class CuentaForm(forms.ModelForm):
    """Una cuenta del plan, con su madre y su naturaleza."""

    class Meta:
        model = Cuenta
        fields = ["codigo", "nombre", "tipo", "naturaleza", "padre", "permite_movimientos", "activa", "descripcion"]
        widgets = {
            "codigo": forms.TextInput(attrs=caja(icono="tag", placeholder="1.1.01.01")),
            "nombre": forms.TextInput(attrs=caja(icono="pencil")),
            "tipo": forms.Select(attrs=desplegable(icono="list")),
            "naturaleza": forms.Select(attrs=desplegable(icono="balance")),
            "padre": forms.Select(attrs=desplegable(icono="arrow-up")),
            "descripcion": forms.Textarea(attrs={"rows": 3, "data-role": "textarea"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["padre"].queryset = Cuenta.objects.order_by("codigo")
        self.fields["padre"].required = False
        self.fields["naturaleza"].required = False
        self.fields["naturaleza"].help_text = (
            "Si se deja vacía se toma la normal del grupo. Las cuentas de corrección "
            "llevan la contraria."
        )


class AsientoForm(forms.ModelForm):
    """Cabecera de un asiento manual."""

    class Meta:
        model = Asiento
        fields = ["fecha", "tipo", "concepto", "referencia", "periodo"]
        widgets = {
            "fecha": forms.DateInput(format="%Y-%m-%d", attrs=fecha()),
            "tipo": forms.Select(attrs=desplegable(icono="history")),
            "concepto": forms.TextInput(attrs=caja(icono="pencil", placeholder="Qué pasó")),
            "referencia": forms.TextInput(attrs=caja(icono="tag", placeholder="Documento que lo respalda")),
            "periodo": forms.Select(attrs=desplegable(icono="calendar")),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["tipo"].choices = [
            (TipoAsiento.DIARIO.value, "Diario"),
            (TipoAsiento.APERTURA.value, "Apertura"),
            (TipoAsiento.AJUSTE.value, "Ajuste"),
        ]
        self.fields["fecha"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.initial.setdefault("fecha", None)
        if not self.initial.get("fecha"):
            self.initial["fecha"] = hoy_en_ecuador()
        self.fields["periodo"].queryset = PeriodoContable.objects.order_by("-fecha_inicio")
        self.fields["periodo"].empty_label = "El periodo del mes"
        self.fields["periodo"].required = False
        self.fields["periodo"].help_text = (
            "Si se deja vacío se usa el periodo del mes de la fecha."
        )

    def clean(self) -> dict:
        datos = super().clean()
        periodo = datos.get("periodo")
        fecha_asiento = datos.get("fecha")
        if periodo and fecha_asiento and not (
            periodo.fecha_inicio <= fecha_asiento <= periodo.fecha_fin
        ):
            raise forms.ValidationError(
                {"fecha": f"La fecha no cae dentro del periodo «{periodo.nombre}»."}
            )
        return datos


class LineaAsientoForm(forms.ModelForm):
    """Una línea: una cuenta al debe o al haber."""

    debe = CampoImporte(label="Debe", required=False, min_value=Decimal("0"))
    haber = CampoImporte(label="Haber", required=False, min_value=Decimal("0"))

    class Meta:
        model = LineaAsiento
        fields = ["cuenta", "descripcion", "debe", "haber", "tercero", "documento"]
        widgets = {
            "cuenta": forms.Select(attrs=desplegable(icono="list")),
            "descripcion": forms.TextInput(attrs=caja(icono="pencil")),
            "tercero": forms.Select(attrs=desplegable(icono="person")),
            "documento": forms.TextInput(attrs=caja(icono="tag")),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = Cuenta.objects.filter(
            activa=True, permite_movimientos=True
        ).order_by("codigo")
        self.fields["cuenta"].empty_label = "Elija una cuenta"
        self.fields["tercero"].queryset = Cliente.objects.order_by("razon_social")
        self.fields["tercero"].empty_label = "Sin tercero"
        self.fields["tercero"].required = False
        self.fields["descripcion"].required = False
        self.fields["documento"].required = False
        self.fields["debe"].widget.attrs.update(numero(icono="arrow-up"))
        self.fields["haber"].widget.attrs.update(numero(icono="arrow-down"))

    def clean(self) -> dict:
        datos = super().clean()
        if not self.has_changed():
            return datos
        debe = datos.get("debe") or CERO
        haber = datos.get("haber") or CERO
        if debe < 0 or haber < 0:
            raise forms.ValidationError("El debe y el haber no pueden ser negativos.")
        if bool(debe) == bool(haber):
            raise forms.ValidationError(
                "Cada línea va al debe o al haber, nunca a los dos ni a ninguno."
            )
        return datos


class BaseAsientoFormSet(BaseInlineFormSet):
    """Comprueba que el asiento tenga líneas y que cuadre."""

    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return
        debe = CERO
        haber = CERO
        cuantas = 0
        for formulario in self.forms:
            if not formulario.cleaned_data or formulario.cleaned_data.get("DELETE"):
                continue
            if not formulario.has_changed():
                continue
            cuantas += 1
            debe += formulario.cleaned_data.get("debe") or CERO
            haber += formulario.cleaned_data.get("haber") or CERO
        if cuantas < 2:
            raise forms.ValidationError("Un asiento necesita al menos dos líneas.")
        if debe != haber:
            raise forms.ValidationError(
                f"El asiento no cuadra: debe {debe:.2f} y haber {haber:.2f}."
            )
        if debe <= CERO:
            raise forms.ValidationError("El asiento no tiene importes.")


formset_de_lineas = inlineformset_factory(
    Asiento,
    LineaAsiento,
    form=LineaAsientoForm,
    formset=BaseAsientoFormSet,
    # Las líneas se añaden desde la ventana; no se dejan formularios vacíos en la
    # página. Que haya al menos dos y que cuadren lo comprueba BaseAsientoFormSet.
    extra=0,
    can_delete=True,
)


class CompraForm(forms.ModelForm):
    """Una factura de compra registrada a mano."""

    class Meta:
        model = Compra
        fields = [
            "proveedor", "tipo_comprobante", "cod_sustento", "numero", "autorizacion",
            "fecha", "concepto", "forma_pago", "base_no_grava", "base_exenta",
            "base_iva_0", "base_iva", "valor_iva", "propina", "total", "cuenta",
            "retencion",
        ]
        widgets = {
            "proveedor": forms.Select(attrs=desplegable(icono="person")),
            "tipo_comprobante": forms.Select(attrs=desplegable(icono="receipt")),
            "cod_sustento": forms.TextInput(attrs=caja(icono="tag", placeholder="01")),
            "numero": forms.TextInput(attrs=caja(icono="tag", placeholder="001001000000001")),
            "autorizacion": forms.TextInput(attrs=caja(icono="key", placeholder="49 dígitos")),
            "fecha": forms.DateInput(format="%Y-%m-%d", attrs=fecha()),
            "concepto": forms.TextInput(attrs=caja(icono="pencil")),
            "forma_pago": forms.TextInput(attrs=caja(icono="credit-card", placeholder="01")),
            "base_no_grava": forms.TextInput(attrs=numero(icono="dollar")),
            "base_exenta": forms.TextInput(attrs=numero(icono="dollar")),
            "base_iva_0": forms.TextInput(attrs=numero(icono="dollar")),
            "base_iva": forms.TextInput(attrs=numero(icono="dollar")),
            "valor_iva": forms.TextInput(attrs=numero(icono="dollar")),
            "propina": forms.TextInput(attrs=numero(icono="dollar")),
            "total": forms.TextInput(attrs=numero(icono="dollar")),
            "cuenta": forms.Select(attrs=desplegable(icono="list")),
            "retencion": forms.Select(attrs=desplegable(icono="percent")),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["fecha"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.initial.setdefault("fecha", None)
        if not self.initial.get("fecha"):
            self.initial["fecha"] = hoy_en_ecuador()
        self.fields["tipo_comprobante"].choices = TipoComprobante.choices
        self.fields["cuenta"].queryset = Cuenta.objects.filter(
            activa=True, permite_movimientos=True
        ).order_by("codigo")
        self.fields["cuenta"].required = False
        self.fields["retencion"].required = False
        self.fields["autorizacion"].required = False
        for campo in (
            "base_no_grava", "base_exenta", "base_iva_0", "base_iva",
            "valor_iva", "propina", "total",
        ):
            self.fields[campo].widget.attrs.update(numero(icono="dollar"))

        config = ConfiguracionContable.activa_actual()
        if config and config.cuenta_compras_gastos_id and not self.initial.get("cuenta"):
            self.initial["cuenta"] = config.cuenta_compras_gastos_id

    def clean_numero(self) -> str:
        numero = "".join(c for c in (self.cleaned_data.get("numero") or "") if c.isdigit())
        if len(numero) != 15:
            raise forms.ValidationError("El número debe tener 15 dígitos (sin guiones).")
        return numero

    def clean(self) -> dict:
        datos = super().clean()
        if not datos.get("cuenta"):
            config = ConfiguracionContable.activa_actual()
            if config and config.cuenta_compras_gastos_id:
                datos["cuenta"] = config.cuenta_compras_gastos
        return datos


class ConfiguracionContableForm(forms.ModelForm):
    """Qué cuenta se usa para cada operación automática."""

    class Meta:
        model = ConfiguracionContable
        exclude = ["creado", "actualizado"]
        widgets = {
            "nombre": forms.TextInput(attrs=caja(icono="pencil")),
            "tipo_empleador": forms.Select(attrs=desplegable(icono="person")),
            "ente_seg_social": forms.Select(attrs=desplegable(icono="bank")),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cuentas = Cuenta.objects.filter(activa=True, permite_movimientos=True).order_by("codigo")
        for nombre, campo in self.fields.items():
            if nombre.startswith("cuenta_"):
                campo.queryset = cuentas
                campo.required = False
                campo.widget.attrs.update(desplegable(icono="list"))


class PeriodoForm(forms.ModelForm):
    """Abrir un periodo contable."""

    class Meta:
        model = PeriodoContable
        fields = ["nombre", "ejercicio", "mes", "fecha_inicio", "fecha_fin"]
        widgets = {
            "nombre": forms.TextInput(attrs=caja(icono="pencil")),
            "mes": forms.NumberInput(attrs={"min": 1, "max": 12, "data-role": "input"}),
            "fecha_inicio": forms.DateInput(format="%Y-%m-%d", attrs=fecha()),
            "fecha_fin": forms.DateInput(format="%Y-%m-%d", attrs=fecha()),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        hoy = hoy_en_ecuador()
        self.initial.setdefault("fecha_inicio", None)
        self.initial.setdefault("fecha_fin", None)
        self.initial.setdefault("ejercicio", None)
        if not self.initial.get("fecha_inicio"):
            self.initial["fecha_inicio"] = hoy.replace(day=1)
        if not self.initial.get("fecha_fin"):
            self.initial["fecha_fin"] = hoy
        if not self.initial.get("ejercicio"):
            self.initial["ejercicio"] = hoy.year
        self.fields["fecha_inicio"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.fields["fecha_fin"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.fields["mes"].required = False


#: Cómo se agrupan los campos del RDEP en la pantalla.
GRUPOS_RDEP = (
    ("Identificación", (
        "anio", "tipo_identificacion", "identificacion", "apellidos", "nombres",
        "establecimiento", "residencia", "pais_residencia", "aplica_convenio",
    )),
    ("Discapacidad y cargas", (
        "ben_galpg", "enf_catastro", "num_carg_reb_gast_pers", "tipo_trabaj_discap",
        "porcentaje_discap", "tip_id_discap", "id_discap",
    )),
    ("Ingresos del año", (
        "suel_sal", "sob_suel_com_remu", "part_util", "int_grab_gen", "imp_rent_empl",
        "decim_ter", "decim_cuar", "fondo_reserva", "salario_digno",
        "otros_ing_ren_grav", "ing_grav_con_este_empl", "sis_sal_net",
    )),
    ("Aportes y deducciones", (
        "apo_per_iess", "apor_per_iess_con_otros_empls", "deduc_vivienda",
        "deduc_salud", "deduc_educa", "deduc_educartcult", "deduc_aliement",
        "deduc_vestim", "deduc_artycult", "deduccion_turismo", "exo_discap",
        "exo_ter_ed",
    )),
    ("Base y retención", (
        "bas_imp", "imp_rent_caus", "rebaja_gastos_personales",
        "impuesto_renta_rebaja_gastos_personales", "val_ret_asu_otros_empls",
        "val_imp_asu_este_empl", "val_ret",
    )),
)


class EmpleadoForm(forms.ModelForm):
    """Ficha anual del empleado para el RDEP."""

    class Meta:
        model = Empleado
        exclude = ["creado", "actualizado"]
        widgets = {
            "anio": forms.NumberInput(attrs={"data-role": "input", "min": 2000, "max": 9999}),
            "tipo_identificacion": forms.Select(attrs=desplegable(icono="person")),
            "identificacion": forms.TextInput(attrs=caja(icono="tag")),
            "apellidos": forms.TextInput(attrs=caja(icono="person")),
            "nombres": forms.TextInput(attrs=caja(icono="person")),
            "establecimiento": forms.TextInput(attrs=caja(icono="home", placeholder="001")),
            "residencia": forms.Select(attrs=desplegable(icono="map")),
            "pais_residencia": forms.TextInput(attrs=caja(icono="map", placeholder="593")),
            "aplica_convenio": forms.Select(attrs=desplegable(icono="globe")),
            "ben_galpg": forms.Select(attrs=desplegable(icono="check")),
            "enf_catastro": forms.Select(attrs=desplegable(icono="heart")),
            "tipo_trabaj_discap": forms.Select(attrs=desplegable(icono="accessibility")),
            "tip_id_discap": forms.Select(attrs=desplegable(icono="person")),
            "id_discap": forms.TextInput(attrs=caja(icono="tag")),
            "sis_sal_net": forms.Select(attrs=desplegable(icono="calculator")),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.initial.setdefault("anio", None)
        if not self.initial.get("anio"):
            self.initial["anio"] = hoy_en_ecuador().year
        for nombre, campo in list(self.fields.items()):
            if isinstance(campo, forms.DecimalField):
                self.fields[nombre] = CampoImporte(
                    label=campo.label,
                    required=False,
                    initial=campo.initial,
                    help_text=campo.help_text,
                    widget=campo.widget,
                )
                self.fields[nombre].widget.attrs.update(numero(icono="dollar"))
        self.fields["id_discap"].required = False
