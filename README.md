# conta_ec

Contabilidad de Ecuador para Django, por partida doble: **plan de cuentas**,
asientos, libros (diario y mayor), balance de comprobación, estados financieros,
cierre, compras y retenciones, anexos del SRI (ATS, RDEP) y empleados.

## Instalación

Desde GitHub:

```bash
pip install "conta_ec @ git+https://github.com/jurdin32/conta_ec.git"
```

Para fijar una versión (recomendado en producción):

```bash
pip install "conta_ec @ git+https://github.com/jurdin32/conta_ec.git@v1.0.0"
```

Y con las pantallas y el admin (Django, el paquete del SRI y el de permisos):

```bash
pip install "conta_ec[django] @ git+https://github.com/jurdin32/conta_ec.git"
```

Para trabajar sobre el paquete, en modo editable desde el clon:

```bash
git clone https://github.com/jurdin32/conta_ec.git
pip install -e ./conta_ec
```

En `INSTALLED_APPS`, después de los comprobantes del SRI:

```python
INSTALLED_APPS = [
    ...,
    "factec.django",      # los comprobantes que se contabilizan
    "conta_ec.django",    # la contabilidad
]
```

Y migrar: `python manage.py migrate`. Ahí se crean las tablas del paquete
(`conta_ec_cuenta`, `conta_ec_asiento`, …), se siembra el plan de cuentas, se dejan
las opciones del menú y quedan sembrados los ajustes.

## Configuración

Los ajustes viven en la tabla del paquete (`conta_ec_ajustedelacontabilidad`) y se
cambian en el admin (**Contabilidad → Ajustes de la contabilidad**). De la
declaración viene todo menos el **valor**:

| clave | de serie | qué hace |
| --- | --- | --- |
| `contabilidad_contabilizar_al_autorizar` | `si` | Al autorizarse un comprobante del SRI, armar su asiento. |
| `contabilidad_periodo_automatico` | `si` | Abrir solo el período del mes de cada asiento. |

No hay archivos `.env`: el paquete no lee variables de entorno.

### Pantallas

El paquete trae las vistas, pero el **aspecto** lo pone el proyecto. Si no se dice
otra cosa, se usan `facturero.marco.marco` y `facturero.controles`; se pueden cambiar
en `settings.py`:

```python
CONTA_EC_MARCO = "mi_proyecto.marco.marco"
CONTA_EC_CAMPOS = "mi_proyecto.controles"
```

## Permisos

Cada pantalla pide su permiso con **personalize_options** (las opciones
`contabilidad`, `plan_cuentas`, `asientos`, …). Si el proyecto no lo tiene puesto, las
pantallas no se pueden usar, pero los modelos, los servicios y los anexos funcionan
igual.

## Pruebas

```bash
python -m pytest src/conta_ec   # o, dentro del proyecto: manage.py test conta_ec
```
