# Contabilidad y anexos del SRI

Este módulo lleva la contabilidad por partida doble y genera los anexos que se
presentan al Servicio de Rentas Internas (SRI) a partir de los comprobantes
autorizados. Todo se apoya en fuentes oficiales; lo que el sistema no puede
deducir se pide en pantalla y, si falta, la generación del anexo se detiene con un
mensaje claro.

## Base legal y técnica

- **Obligación de llevar contabilidad**: Ley de Régimen Tributario Interno
  (LORTI), artículo 19 y su Reglamento.
- **Libros de comercio**: Código de Comercio del Ecuador (libro diario, libro
  mayor, inventarios y balances).
- **Estados financieros**: Normas Internacionales de Información Financiera
  (NIIF y NIIF para PYMES), exigidas por la Superintendencia de Compañías,
  Valores y Seguros. El **Plan de Cuentas** inicial sigue la estructura de cinco
  grupos de la Superintendencia (activo, pasivo, patrimonio, ingresos y
  costos/gastos) y es editable.
- **Comprobantes electrónicos**: esquemas del SRI para factura, nota de crédito,
  nota de débito, liquidación de compra, guía de remisión y comprobante de
  retención (los emite el paquete `factec`).
- **ATS**: Anexo Transaccional Simplificado. Resolución
  **NAC-DGERCGC12-00001** (Registro Oficial 618, 13 de enero de 2012) y sus
  reformas. Estructura validada contra el XSD oficial
  `https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd`.
- **REOC**: Anexo de Retenciones en la Fuente por Otros Conceptos. Estructura
  validada contra `https://descargas.sri.gob.ec/download/anexos/reoc/reoc.xsd`.
- **RDEP**: Anexo de Retenciones en la Fuente bajo Relación de Dependencia.
  Artículo 43 de la LORTI y Resolución **NAC-DGERCGC24-00000002**. Estructura
  validada contra el esquema oficial **RDEP 2023** del SRI.
- **IVA**: tarifa vigente del 15 % (código `4` de la tabla 16 del SRI), además de
  0 %, 5 %, no objeto y exento. Los códigos de retención de renta e IVA son los de
  las tablas 17 y 20 del SRI.

## Qué hace el módulo

1. **Plan de cuentas jerárquico** con niveles (`1`, `1.1`, `1.1.01`,
   `1.1.01.01`), naturaleza deudora/acreedora y cuentas de suma.
2. **Asientos** con debe y haber, validación de partida doble, periodos abiertos,
   numeración correlativa, anulación con historia y asientos automáticos.
3. **Contabilización automática** al autorizarse un comprobante:
   - factura: cuentas por cobrar, ventas e IVA por pagar (y retenciones que
     retiene el cliente);
   - nota de crédito: reverso de la venta;
   - nota de débito: cuentas por cobrar, otros ingresos e IVA;
   - liquidación de compra: gasto/inventario, IVA crédito y cuentas por pagar;
   - retención: crea la compra del documento sustento (si no existe) y registra
     el pasivo por renta, IVA o ISD retenido.
4. **Compras** registradas a mano o creadas por la retención, con sus bases
   (no objeto, exenta, 0 %, gravada), IVA y total.
5. **Libros**: diario, mayor, balance de comprobación.
6. **Estados financieros**: resultados, situación financiera, flujos de efectivo
   (método directo) y cambios en el patrimonio.
7. **Cierre**: cierre de periodos y cierre anual contra resultado del ejercicio y
   resultados acumulados, con reapertura.
8. **Anexos**: ATS, REOC y RDEP en XML; registro de compras y ventas en CSV para
   revisión. Además, resúmenes de IVA (104) y retenciones (103).

## Criterios de mapeo del ATS

El XSD oficial distingue estas bases, y el módulo las usa así:

| Campo del ATS | Qué lleva |
|---|---|
| `baseNoGraIva` | Base imponible **no objeto** de IVA |
| `baseImponible` | Base imponible con tarifa **0 %** |
| `baseImpGrav` | Base imponible con tarifa **distinta de 0 %** |
| `baseImpExe` | Base **exenta** (solo en compras) |

En ventas, el ATS no tiene `baseImpExe`: lo exento se informa en `baseNoGraIva`.
Las fechas van como **DD/MM/AAAA** y los importes con punto decimal y dos
decimales, como exige el esquema. Las notas de crédito se informan con su tipo de
comprobante `04` y valores positivos; `totalVentas` se calcula con su signo.

Las retenciones de IVA de la tabla 20 se reparten en los campos del ATS:

| Código | Campo del ATS |
|---|---|
| 721 | `valorRetBienes` |
| 723 | `valorRetServicios` |
| 725 | `valRetBien10` |
| 727 | `valRetServ20` |
| 729 | `valRetServ50` |
| 731 | `valRetServ100` |

Las retenciones de renta no van en esos campos: van en el **REOC**.

El **código de sustento** (tabla 5 del SRI) decide el tratamiento del IVA de la
compra:

| `codSustento` | Tratamiento del IVA |
|---|---|
| `01` crédito tributario de IVA | Va a `1.1.04.01 IVA crédito tributario`. |
| `02`, `03` u otro sin derecho a crédito | Se suma al costo o gasto de la compra; no se usa la cuenta de crédito. |

## Límites deliberados (para no inventar datos)

- El ATS se genera con **compras registradas** y **ventas electrónicas
  autorizadas**. No incluye exportaciones, reembolsos, recap, fideicomisos ni
  compensaciones porque este sistema no los captura; el XSD los admite como
  opcionales y se omiten. Tampoco se capturan compras al exterior ni notas de
  crédito de proveedores: esos casos se ajustan a mano en la contabilidad y se
  informan en el portal/DIMM si el negocio los tiene.
- El apartado `anulados` del ATS se omite: en facturación electrónica un
  comprobante autorizado no se “anula” con otro estado, se corrige con una nota de
  crédito, que sí se informa.
- El **RDEP no es una nómina**: pide los rubros anuales por empleado. Si el
  negocio lleva su nómina en otro sistema, esos valores se registran en la ficha
  del empleado. El módulo no calcula décimos, fondos de reserva ni impuesto a la
  renta del trabajador.
- La firma electrónica y el envío al SRI se hacen con el paquete `factec` y el
  portal/DIMM del SRI. Este módulo genera los archivos, no los firma ni los
  transmite.
- La declaración de IVA (104) y la de retenciones (103) son **resúmenes de
  trabajo**; se presentan en el portal del SRI.

## Comandos

```bash
python manage.py sembrar_plan_cuentas          # crea las cuentas que falten
python manage.py contabilizar_comprobantes     # contabiliza autorizados sin asiento
```

## Referencias oficiales

- XSD del ATS: `https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd`
- XSD del REOC: `https://descargas.sri.gob.ec/download/anexos/reoc/reoc.xsd`
- Esquema RDEP 2023: publicado por el SRI en «Anexos y guías».
- Plan de cuentas de la Superintendencia de Compañías:
  `https://www.supercias.gob.ec/bd_supercias/formularios/Formularios e Instructivos/PLAN DE CUENTAS.pdf`
