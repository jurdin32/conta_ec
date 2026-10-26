"""Las pantallas de la contabilidad.

El día a día son tres: el plan de cuentas, los asientos y los informes. Los anexos
del SRI se descargan desde una sola pantalla, con el mes o el año elegido. Todo se
apoya en los servicios (:mod:`servicios`) y en los informes (:mod:`informes`), que
son los que saben de partida doble; aquí solo se pinta.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from factec.django.models import ComprobanteEmitido, EstadoComprobante
from factec.sri.fechas import hoy_en_ecuador
from personalize_options.decoradores import exigir_escritura, requiere_lectura

from .ui import marco

from . import anexos, informes, servicios
from .forms import (
    GRUPOS_RDEP,
    AsientoForm,
    CompraForm,
    ConfiguracionContableForm,
    CuentaForm,
    EmpleadoForm,
    PeriodoForm,
    formset_de_lineas,
)
from .models import (
    CERO,
    Asiento,
    Compra,
    ConfiguracionContable,
    Cuenta,
    Empleado,
    EstadoAsiento,
    PeriodoContable,
    TipoAsiento,
)

__all__ = [
    "anexos_sri", "asiento", "asiento_accion", "asiento_detalle", "asientos",
    "balance", "cierre", "compra", "compras", "configuracion", "contabilizar_pendientes",
    "cuenta", "descargar", "empleado", "empleados", "estado_flujos", "estado_patrimonio",
    "estado_resultados", "estado_situacion", "estado_situacion_inicial", "estados",
    "iva", "libro_diario",
    "libro_mayor", "plan", "retenciones", "tablero",
]


# ------------------------------------------------------------------ ayudas


def _hoy() -> date:
    return hoy_en_ecuador()


def _inicio_mes(valor: date) -> date:
    return valor.replace(day=1)


def _fin_mes(valor: date) -> date:
    siguiente = (valor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return siguiente - timedelta(days=1)


def _fechas(
    request: HttpRequest,
    desde_por_defecto: Optional[date] = None,
    hasta_por_defecto: Optional[date] = None,
) -> tuple[date, date]:
    hoy = _hoy()
    desde = parse_date(request.GET.get("desde") or "") or desde_por_defecto or _inicio_mes(hoy)
    hasta = parse_date(request.GET.get("hasta") or "") or hasta_por_defecto or hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


def _anio_mes(request: HttpRequest) -> tuple[int, int]:
    hoy = _hoy()
    try:
        anio = int(request.GET.get("anio") or hoy.year)
    except ValueError:
        anio = hoy.year
    try:
        mes = int(request.GET.get("mes") or hoy.month)
    except ValueError:
        mes = hoy.month
    if not (2000 <= anio <= 9999):
        anio = hoy.year
    if not (1 <= mes <= 12):
        mes = hoy.month
    return anio, mes


def _config() -> Optional[ConfiguracionContable]:
    return ConfiguracionContable.activa_actual()


def _contexto(request: HttpRequest, **extra: Any) -> dict[str, Any]:
    config = _config()
    contexto = {
        **marco(request),
        "config": config,
        "faltantes": config.faltantes() if config else [],
        "hoy": _hoy(),
    }
    contexto.update(extra)
    return contexto


def _guardar_mensajes(request: HttpRequest, error: Exception) -> None:
    if isinstance(error, ValidationError):
        for mensaje in error.messages:
            messages.error(request, mensaje)
    else:
        messages.error(request, str(error))


# ------------------------------------------------------------------ tablero


@login_required
@requiere_lectura("contabilidad")
def tablero(request: HttpRequest) -> HttpResponse:
    hoy = _hoy()
    desde, hasta = _inicio_mes(hoy), _fin_mes(hoy)
    config = _config()

    resultado = informes.estado_resultados(desde, hoy)
    situacion = informes.estado_situacion(hoy) if config else None
    iva = informes.resumen_iva(hoy.year, hoy.month)
    recientes = (
        Asiento.objects.select_related("periodo")
        .annotate(debe_total=Sum("lineas__debe"), haber_total=Sum("lineas__haber"))
        .order_by("-fecha", "-pk")[:8]
    )
    con_asiento = Asiento.objects.filter(comprobante__isnull=False).values("comprobante_id")
    pendientes = (
        ComprobanteEmitido.objects.filter(estado=EstadoComprobante.AUTORIZADO.value)
        .exclude(pk__in=con_asiento)
        .count()
    )
    por_contabilizar = Asiento.objects.filter(estado=EstadoAsiento.BORRADOR.value).count()

    return render(
        request,
        "contabilidad/tablero.html",
        _contexto(
            request,
            desde=desde,
            hasta=hasta,
            resultado=resultado,
            situacion=situacion,
            iva=iva,
            recientes=recientes,
            pendientes=pendientes,
            por_contabilizar=por_contabilizar,
            cuentas=Cuenta.objects.count(),
            asientos_mes=Asiento.objects.filter(
                fecha__gte=desde, fecha__lte=hasta,
                estado=EstadoAsiento.CONTABILIZADO.value,
            ).count(),
        ),
    )


@login_required
@require_POST
def contabilizar_pendientes(request: HttpRequest) -> HttpResponse:
    """Contabiliza de una vez los autorizados que quedaron sin asiento."""
    exigir_escritura(request, "asientos")
    resultado = servicios.contabilizar_pendientes(usuario=request.user)
    if resultado["contabilizados"]:
        messages.success(
            request,
            f"{resultado['contabilizados']} comprobante(s) contabilizados.",
        )
    else:
        messages.info(request, "No había comprobantes pendientes de contabilizar.")
    for error in resultado["errores"]:
        messages.error(request, error)
    return redirect("contabilidad:tablero")


# ------------------------------------------------------------- plan de cuentas


@login_required
@requiere_lectura("plan_cuentas")
def plan(request: HttpRequest) -> HttpResponse:
    hoy = _hoy()
    cuentas = list(Cuenta.objects.all().order_by("codigo"))
    texto = (request.GET.get("q") or "").strip()
    tipo = request.GET.get("tipo") or ""
    if tipo:
        cuentas = [cuenta for cuenta in cuentas if cuenta.tipo == tipo]
    if texto:
        buscado = texto.lower()
        cuentas = [
            cuenta for cuenta in cuentas
            if buscado in cuenta.codigo.lower() or buscado in cuenta.nombre.lower()
        ]
    filas = []
    for cuenta in cuentas:
        filas.append(
            {
                "cuenta": cuenta,
                "saldo": cuenta.saldo(hasta=hoy),
                "propio": cuenta.saldo_directo(hasta=hoy),
                "hijas": cuenta.hijas.exists(),
            }
        )
    return render(
        request,
        "contabilidad/plan.html",
        _contexto(
            request,
            filas=filas,
            filtros={"q": texto, "tipo": tipo},
            tipos=[
                ("activo", "Activo"), ("pasivo", "Pasivo"),
                ("patrimonio", "Patrimonio"), ("ingreso", "Ingreso"),
                ("costo", "Costo"), ("gasto", "Gasto"),
            ],
        ),
    )


@login_required
@requiere_lectura("plan_cuentas")
def cuenta(request: HttpRequest, pk: Optional[int] = None) -> HttpResponse:
    instancia = get_object_or_404(Cuenta, pk=pk) if pk else Cuenta()
    if request.method == "POST":
        exigir_escritura(request, "plan_cuentas")
        formulario = CuentaForm(request.POST, instance=instancia)
        if formulario.is_valid():
            try:
                formulario.save()
            except ValidationError as error:
                _guardar_mensajes(request, error)
            else:
                messages.success(request, "Cuenta guardada.")
                return redirect("contabilidad:plan")
    else:
        formulario = CuentaForm(instance=instancia)
    return render(
        request,
        "contabilidad/cuenta.html",
        _contexto(request, formulario=formulario, cuenta=instancia, es_nueva=not pk),
    )


# ----------------------------------------------------------------- asientos


@login_required
@requiere_lectura("asientos")
def asientos(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(
        request, date(_hoy().year, 1, 1), _hoy()
    )
    consulta = (
        Asiento.objects.select_related("periodo", "comprobante")
        .annotate(debe_total=Sum("lineas__debe"), haber_total=Sum("lineas__haber"))
        .filter(fecha__gte=desde, fecha__lte=hasta)
        .order_by("-fecha", "-pk")
    )
    texto = (request.GET.get("q") or "").strip()
    estado = request.GET.get("estado") or ""
    tipo = request.GET.get("tipo") or ""
    if texto:
        consulta = consulta.filter(
            models_q(texto)
        )
    if estado:
        consulta = consulta.filter(estado=estado)
    if tipo:
        consulta = consulta.filter(tipo=tipo)

    paginador = Paginator(consulta, 30)
    pagina = paginador.get_page(request.GET.get("pagina"))
    return render(
        request,
        "contabilidad/asientos.html",
        _contexto(
            request,
            filas=pagina,
            desde=desde,
            hasta=hasta,
            filtros={"q": texto, "estado": estado, "tipo": tipo},
            estados=EstadoAsiento.choices,
            tipos=[t for t in TipoAsiento.choices if t[0] != TipoAsiento.CIERRE.value],
            cuantos=paginador.count,
        ),
    )


def models_q(texto: str) -> Any:
    from django.db.models import Q

    return (
        Q(numero__icontains=texto)
        | Q(concepto__icontains=texto)
        | Q(referencia__icontains=texto)
    )


@login_required
@requiere_lectura("asientos")
def asiento(request: HttpRequest, pk: Optional[int] = None) -> HttpResponse:
    instancia = get_object_or_404(Asiento, pk=pk) if pk else Asiento()
    if instancia.pk and not instancia.editable:
        messages.error(request, "Un asiento contabilizado no se edita: anúlelo y haga otro.")
        return redirect("contabilidad:asiento_detalle", pk=instancia.pk)

    if request.method == "POST":
        exigir_escritura(request, "asientos")
        formulario = AsientoForm(request.POST, instance=instancia)
        conjunto = formset_de_lineas(request.POST, instance=instancia)
        if formulario.is_valid() and conjunto.is_valid():
            try:
                asiento_guardado = formulario.save(commit=False)
                asiento_guardado.usuario = request.user
                asiento_guardado.save()
                conjunto.instance = asiento_guardado
                conjunto.save()
                if request.POST.get("accion") == "contabilizar":
                    asiento_guardado.contabilizar(usuario=request.user)
                    messages.success(request, f"Asiento {asiento_guardado.numero} contabilizado.")
                else:
                    messages.success(request, "Asiento guardado como borrador.")
                return redirect("contabilidad:asiento_detalle", pk=asiento_guardado.pk)
            except ValidationError as error:
                _guardar_mensajes(request, error)
    else:
        formulario = AsientoForm(instance=instancia)
        conjunto = formset_de_lineas(instance=instancia)

    return render(
        request,
        "contabilidad/asiento.html",
        _contexto(
            request,
            formulario=formulario,
            conjunto=conjunto,
            asiento=instancia,
            es_nuevo=not pk,
            tipos=TipoAsiento,
        ),
    )


@login_required
@requiere_lectura("asientos")
def asiento_detalle(request: HttpRequest, pk: int) -> HttpResponse:
    instancia = get_object_or_404(
        Asiento.objects.select_related("periodo", "comprobante").prefetch_related("lineas__cuenta"),
        pk=pk,
    )
    return render(
        request,
        "contabilidad/asiento_detalle.html",
        _contexto(request, asiento=instancia, lineas=instancia.lineas.all()),
    )


@login_required
@require_POST
def asiento_accion(request: HttpRequest, pk: int, que: str) -> HttpResponse:
    exigir_escritura(request, "asientos")
    instancia = get_object_or_404(Asiento, pk=pk)
    try:
        if que == "contabilizar":
            instancia.contabilizar(usuario=request.user)
            messages.success(request, f"Asiento {instancia.numero} contabilizado.")
        elif que == "anular":
            instancia.anular(request.POST.get("motivo", ""), usuario=request.user)
            messages.success(request, "Asiento anulado. Ya no cuenta en los saldos.")
        else:
            raise Http404("Acción desconocida")
    except ValidationError as error:
        _guardar_mensajes(request, error)
    return redirect("contabilidad:asiento_detalle", pk=instancia.pk)


# --------------------------------------------------------------- libros


@login_required
@requiere_lectura("libro_diario")
def libro_diario(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    datos = informes.libro_diario(desde, hasta)
    return render(
        request,
        "contabilidad/libro_diario.html",
        _contexto(request, desde=desde, hasta=hasta, **datos),
    )


@login_required
@requiere_lectura("libro_mayor")
def libro_mayor(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    cuentas = Cuenta.objects.filter(activa=True, permite_movimientos=True).order_by("codigo")
    pk = request.GET.get("cuenta")
    cuenta_actual = None
    if pk:
        cuenta_actual = get_object_or_404(Cuenta, pk=pk)
    elif cuentas.exists():
        cuenta_actual = cuentas.first()
    datos = informes.libro_mayor(cuenta_actual, desde, hasta) if cuenta_actual else None
    return render(
        request,
        "contabilidad/libro_mayor.html",
        _contexto(
            request,
            desde=desde,
            hasta=hasta,
            cuentas=cuentas,
            cuenta_actual=cuenta_actual,
            datos=datos,
        ),
    )


@login_required
@requiere_lectura("balance_comprobacion")
def balance(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    datos = informes.balance_comprobacion(desde, hasta)
    return render(
        request,
        "contabilidad/balance.html",
        _contexto(request, desde=desde, hasta=hasta, **datos),
    )


@login_required
@requiere_lectura("estados_financieros")
def estados(request: HttpRequest) -> HttpResponse:
    hoy = _hoy()
    desde = date(hoy.year, 1, 1)
    resultado = informes.estado_resultados(desde, hoy)
    situacion = informes.estado_situacion(hoy)
    return render(
        request,
        "contabilidad/estados.html",
        _contexto(
            request, desde=desde, hasta=hoy, resultado=resultado, situacion=situacion
        ),
    )


@login_required
@requiere_lectura("estados_financieros")
def estado_resultados(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    datos = informes.estado_resultados(desde, hasta)
    return render(
        request,
        "contabilidad/estado_resultados.html",
        _contexto(request, **datos),
    )


@login_required
@requiere_lectura("estados_financieros")
def estado_situacion(request: HttpRequest) -> HttpResponse:
    hasta = parse_date(request.GET.get("hasta") or "") or _hoy()
    datos = informes.estado_situacion(hasta)
    return render(
        request,
        "contabilidad/estado_situacion.html",
        _contexto(request, **datos),
    )


@login_required
@requiere_lectura("estado_inicial")
def estado_situacion_inicial(request: HttpRequest) -> HttpResponse:
    """Los saldos con los que abre el ejercicio, antes de las operaciones."""
    hasta = parse_date(request.GET.get("hasta") or "") or date(_hoy().year, 1, 1)
    datos = informes.estado_situacion(hasta)
    return render(
        request,
        "contabilidad/estado_situacion.html",
        _contexto(request, es_inicial=True, **datos),
    )


@login_required
@requiere_lectura("estados_financieros")
def estado_flujos(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    config = _config()
    datos = informes.estado_flujos(desde, hasta, config) if config else None
    return render(
        request,
        "contabilidad/estado_flujos.html",
        _contexto(request, desde=desde, hasta=hasta, datos=datos),
    )


@login_required
@requiere_lectura("estados_financieros")
def estado_patrimonio(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    datos = informes.estado_patrimonio(desde, hasta)
    return render(
        request,
        "contabilidad/estado_patrimonio.html",
        _contexto(request, **datos),
    )


# ------------------------------------------------------------------ cierre


@login_required
@requiere_lectura("cierre_contable")
def cierre(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        exigir_escritura(request, "cierre_contable")
        accion = request.POST.get("accion")
        try:
            if accion == "periodo":
                formulario = PeriodoForm(request.POST)
                if formulario.is_valid():
                    formulario.save()
                    messages.success(request, "Periodo creado.")
                else:
                    for errores in formulario.errors.values():
                        for texto in errores:
                            messages.error(request, texto)
                return redirect("contabilidad:cierre")
            if accion == "cerrar":
                periodo = get_object_or_404(PeriodoContable, pk=request.POST.get("periodo"))
                if Asiento.objects.filter(
                    periodo=periodo, estado=EstadoAsiento.BORRADOR.value
                ).exists():
                    raise ValidationError(
                        "Ese periodo tiene asientos en borrador: contabilícelos o bórrelos."
                    )
                periodo.estado = PeriodoContable.Estado.CERRADO.value
                periodo.save(update_fields=["estado", "actualizado"])
                messages.success(request, f"Periodo «{periodo.nombre}» cerrado.")
            elif accion == "reabrir":
                periodo = get_object_or_404(PeriodoContable, pk=request.POST.get("periodo"))
                periodo.estado = PeriodoContable.Estado.ABIERTO.value
                periodo.save(update_fields=["estado", "actualizado"])
                messages.success(request, f"Periodo «{periodo.nombre}» reabierto.")
            elif accion == "cerrar_ejercicio":
                anio = int(request.POST.get("anio") or _hoy().year)
                servicios.cerrar_ejercicio(anio, usuario=request.user)
                messages.success(request, f"Ejercicio {anio} cerrado.")
            elif accion == "reabrir_ejercicio":
                anio = int(request.POST.get("anio") or _hoy().year)
                servicios.reabrir_ejercicio(anio, usuario=request.user)
                messages.success(request, f"Ejercicio {anio} reabierto.")
        except (ValidationError, ValueError) as error:
            _guardar_mensajes(request, error)
        return redirect("contabilidad:cierre")

    periodos = PeriodoContable.objects.order_by("-fecha_inicio")
    formulario = PeriodoForm()
    return render(
        request,
        "contabilidad/cierre.html",
        _contexto(request, periodos=periodos, formulario=formulario),
    )


# ---------------------------------------------------------------- compras


@login_required
@requiere_lectura("compras")
def compras(request: HttpRequest) -> HttpResponse:
    desde, hasta = _fechas(request, date(_hoy().year, 1, 1), _hoy())
    consulta = Compra.objects.select_related("proveedor", "retencion", "asiento").filter(
        fecha__gte=desde, fecha__lte=hasta
    ).order_by("-fecha", "-pk")
    texto = (request.GET.get("q") or "").strip()
    if texto:
        from django.db.models import Q

        consulta = consulta.filter(
            Q(numero__icontains=texto)
            | Q(proveedor__razon_social__icontains=texto)
            | Q(concepto__icontains=texto)
        )
    filas = list(consulta)
    return render(
        request,
        "contabilidad/compras.html",
        _contexto(
            request,
            filas=filas,
            desde=desde,
            hasta=hasta,
            filtros={"q": texto},
            total=sum((fila.total for fila in filas), CERO),
            sin_contabilizar=sum(1 for fila in filas if fila.asiento_id is None),
        ),
    )


@login_required
@requiere_lectura("compras")
def compra(request: HttpRequest, pk: Optional[int] = None) -> HttpResponse:
    instancia = get_object_or_404(Compra, pk=pk) if pk else Compra()
    if request.method == "POST":
        exigir_escritura(request, "compras")
        formulario = CompraForm(request.POST, instance=instancia)
        if formulario.is_valid():
            try:
                compra_guardada = formulario.save()
                if request.POST.get("accion") == "contabilizar":
                    servicios.contabilizar_compra(compra_guardada, usuario=request.user)
                    messages.success(request, "Compra guardada y contabilizada.")
                else:
                    messages.success(request, "Compra guardada.")
                return redirect("contabilidad:compras")
            except ValidationError as error:
                _guardar_mensajes(request, error)
    else:
        formulario = CompraForm(instance=instancia)
    return render(
        request,
        "contabilidad/compra.html",
        _contexto(request, formulario=formulario, compra=instancia, es_nueva=not pk),
    )


# ------------------------------------------------------------- configuración


@login_required
@requiere_lectura("configuracion_contable")
def configuracion(request: HttpRequest) -> HttpResponse:
    instancia = _config() or ConfiguracionContable()
    if request.method == "POST":
        exigir_escritura(request, "configuracion_contable")
        formulario = ConfiguracionContableForm(request.POST, instance=instancia)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, "Configuración contable guardada.")
            return redirect("contabilidad:configuracion")
    else:
        formulario = ConfiguracionContableForm(instance=instancia)
    return render(
        request,
        "contabilidad/configuracion.html",
        _contexto(request, formulario=formulario, instancia=instancia),
    )


# ------------------------------------------------------------------ anexos


@login_required
@requiere_lectura("anexos_sri")
def anexos_sri(request: HttpRequest) -> HttpResponse:
    anio, mes = _anio_mes(request)
    try:
        resumen = informes.resumen_ats(anio, mes)
        iva = informes.resumen_iva(anio, mes)
        retenciones = informes.resumen_retenciones(anio, mes)
    except Exception as error:  # noqa: BLE001 - se enseña el problema en la pantalla
        resumen = None
        iva = None
        retenciones = None
        messages.error(request, str(error))
    empleados = Empleado.objects.filter(anio=anio, activo=True).order_by("apellidos", "nombres")
    return render(
        request,
        "contabilidad/anexos.html",
        _contexto(
            request,
            anio=anio,
            mes=mes,
            resumen=resumen,
            iva=iva,
            retenciones=retenciones,
            empleados=empleados,
            total_retenido=retenciones["total"] if retenciones else CERO,
        ),
    )


@login_required
@requiere_lectura("anexos_sri")
def descargar(request: HttpRequest, que: str) -> HttpResponse:
    anio, mes = _anio_mes(request)
    try:
        if que == "ats":
            contenido = anexos.generar_ats_xml(anio, mes)
            nombre = f"ATS_{anio}_{mes:02d}.xml"
            tipo = "application/xml"
        elif que == "reoc":
            contenido = anexos.generar_reoc_xml(anio, mes)
            nombre = f"REOC_{anio}_{mes:02d}.xml"
            tipo = "application/xml"
        elif que == "rdep":
            contenido = anexos.generar_rdep_xml(anio)
            nombre = f"RDEP_{anio}.xml"
            tipo = "application/xml"
        elif que == "compras-ventas":
            contenido = anexos.generar_csv_compras_ventas(anio, mes)
            nombre = f"COMPRAS_VENTAS_{anio}_{mes:02d}.csv"
            tipo = "text/csv; charset=utf-8"
        else:
            raise Http404("Anexo desconocido")
    except ValidationError as error:
        for mensaje in error.messages:
            messages.error(request, mensaje)
        return redirect("contabilidad:anexos")
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


# ---------------------------------------------------------------- RDEP


@login_required
@requiere_lectura("empleados")
def empleados(request: HttpRequest) -> HttpResponse:
    try:
        anio = int(request.GET.get("anio") or _hoy().year)
    except ValueError:
        anio = _hoy().year
    if not (2000 <= anio <= 9999):
        anio = _hoy().year
    filas = Empleado.objects.filter(anio=anio).order_by("apellidos", "nombres")
    return render(
        request,
        "contabilidad/empleados.html",
        _contexto(
            request,
            filas=filas,
            anio=anio,
            total_sueldos=sum((fila.suel_sal for fila in filas), CERO),
            total_retenido=sum((fila.val_ret for fila in filas), CERO),
        ),
    )


@login_required
@requiere_lectura("empleados")
def empleado(request: HttpRequest, pk: Optional[int] = None) -> HttpResponse:
    instancia = get_object_or_404(Empleado, pk=pk) if pk else Empleado()
    if request.method == "POST":
        exigir_escritura(request, "empleados")
        formulario = EmpleadoForm(request.POST, instance=instancia)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, "Ficha del empleado guardada.")
            return redirect("contabilidad:empleados")
    else:
        formulario = EmpleadoForm(instance=instancia)
    return render(
        request,
        "contabilidad/empleado.html",
        _contexto(
            request,
            formulario=formulario,
            empleado=instancia,
            es_nuevo=not pk,
            grupos=GRUPOS_RDEP,
        ),
    )


# ------------------------------------------------------------ IVA y 103


@login_required
@requiere_lectura("anexos_sri")
def iva(request: HttpRequest) -> HttpResponse:
    anio, mes = _anio_mes(request)
    datos = informes.resumen_iva(anio, mes)
    return render(
        request,
        "contabilidad/iva.html",
        _contexto(request, **datos),
    )


@login_required
@requiere_lectura("anexos_sri")
def retenciones(request: HttpRequest) -> HttpResponse:
    anio, mes = _anio_mes(request)
    datos = informes.resumen_retenciones(anio, mes)
    return render(
        request,
        "contabilidad/retenciones.html",
        _contexto(request, **datos),
    )
