# Modelo Power BI / Power BI model

## Español

### Carga y configuración

1. Ejecute `make powerbi` y abra Power BI Desktop con la configuración regional
   del archivo en **Español (Chile) / `es-CL`**.
2. Use **Obtener datos → Parquet** para cargar los seis archivos de
   `data/powerbi/`. Mantenga como nombres de tabla `fact_cartera`,
   `fact_expedientes`, `agg_km`, `agg_cif`, `agg_tendencia` y
   `kpi_validados`.
3. En `fact_cartera`, ordene `estado_ambiental_label_es` por
   `estado_ambiental_orden`.
4. No agregue columnas de texto desde los artefactos de origen. La exportación
   ya excluye titulares, personas, números de RCA, historial y texto largo.

Los Parquet fijan las fechas como `date32` y todas las columnas con un tipo
Arrow explícito. Los formatos numéricos se aplican a las medidas, no a las
columnas fuente.

### Relaciones

Cree únicamente estas relaciones:

- `Calendario[Date]` 1→* `fact_expedientes[fecha_ingreso]`, activa, filtro en
  una dirección desde `Calendario`.
- `Calendario[Date]` 1→* `fact_cartera[fecha_ingreso]`, inactiva, filtro en una
  dirección desde `Calendario`.

`agg_km`, `agg_cif`, `agg_tendencia` y `kpi_validados` quedan sin relaciones.
Son tablas de resultados ya agregados o valores escalares y relacionarlas
alteraría sus cifras.

### Tabla Calendario

Pegue esta tabla calculada. Los separadores `;` corresponden al locale
`es-CL`; si Desktop está configurado para separadores DAX invariantes, cámbielos
por comas.

```DAX
Calendario =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2011; 1; 1 ); DATE ( 2034; 12; 31 ) );
    "Año"; YEAR ( [Date] );
    "Mes número"; MONTH ( [Date] );
    "Mes"; FORMAT ( [Date]; "[$-es-CL]mmm" );
    "Año-mes"; FORMAT ( [Date]; "yyyy-MM" );
    "Trimestre"; "T" & FORMAT ( [Date]; "Q" )
)
```

Marque `Calendario` como tabla de fechas usando `Calendario[Date]` y ordene
`Calendario[Mes]` por `Calendario[Mes número]`.

### Medidas DAX y formatos

Cree las medidas en una tabla dedicada llamada `_Medidas`. Después de pegar
cada fórmula, asigne en **Herramientas de medida → Formato → Personalizado** el
formato indicado. De este modo el formato viaja con la medida y no depende del
tipo detectado para una columna.

```DAX
Inversión total =
SUM ( fact_cartera[inversion_musd] )
```

Formato: `#,##0.0 "MMUS$"`

```DAX
Inversión por estado =
SUM ( fact_cartera[inversion_musd] )
```

Formato: `#,##0.0 "MMUS$"`

```DAX
% del total =
DIVIDE (
    [Inversión por estado];
    CALCULATE (
        [Inversión total];
        REMOVEFILTERS (
            fact_cartera[estado_ambiental];
            fact_cartera[estado_ambiental_label_es];
            fact_cartera[estado_ambiental_orden]
        )
    )
)
```

Formato: `0.0%`

```DAX
N proyectos =
DISTINCTCOUNT ( fact_cartera[project_id] )
```

Formato: `#,##0`

```DAX
N expedientes =
DISTINCTCOUNT ( fact_expedientes[exp_id] )
```

Formato: `#,##0`

```DAX
Mediana meses =
MEDIANX ( fact_expedientes; fact_expedientes[duracion_meses] )
```

Formato: `0.0 "meses"`

```DAX
Tasa de desistimiento =
DIVIDE (
    CALCULATE (
        [N expedientes];
        KEEPFILTERS (
            fact_expedientes[evento] = "desistido_o_abandonado"
        )
    );
    [N expedientes]
)
```

Formato: `0.0%`

```DAX
KPI inversión cartera =
LOOKUPVALUE (
    kpi_validados[valor];
    kpi_validados[claim_id]; "cartera_inversion_total"
)
```

Formato: `#,##0.0 "MMUS$"`

```DAX
KPI proyectos cartera =
LOOKUPVALUE (
    kpi_validados[valor];
    kpi_validados[claim_id]; "cartera_proyectos_n"
)
```

Formato: `#,##0`

```DAX
KPI expedientes admitidos =
LOOKUPVALUE (
    kpi_validados[valor];
    kpi_validados[claim_id]; "sea_poblacion_admitida_n"
)
```

Formato: `#,##0`

```DAX
KPI inversión sin expediente en estudio =
LOOKUPVALUE (
    kpi_validados[valor];
    kpi_validados[claim_id]; "estado_sin_expediente_en_estudio_inversion"
)
```

Formato: `#,##0.0 "MMUS$"`

```DAX
KPI % sin expediente en estudio =
DIVIDE (
    LOOKUPVALUE (
        kpi_validados[valor];
        kpi_validados[claim_id]; "estado_sin_expediente_en_estudio_pct"
    );
    100
)
```

Formato: `0.0%`

### Diseño exacto de las tres páginas

#### 1. Cartera

- Fila superior: cuatro tarjetas, en este orden: `KPI inversión cartera`,
  `KPI proyectos cartera`, `KPI inversión sin expediente en estudio` y
  `KPI % sin expediente en estudio`.
- Izquierda: gráfico de barras horizontales; eje Y
  `fact_cartera[estado_ambiental_label_es]`, eje X
  `[Inversión por estado]`, etiqueta adicional en tooltip `[% del total]`.
- Derecha: gráfico de barras agrupadas; eje Y `fact_cartera[region]`, eje X
  `[Inversión total]`, orden descendente. Se eligen barras —no mapa— para evitar
  ambigüedad geográfica y dependencia de geocodificación.
- Abajo: tabla con `nombre_proyecto`, `empresa`, `mina`, `region`, `etapa`,
  `condicion`, `pem_inicio`, `pem_fin`, `inversion_musd` y
  `estado_ambiental_label_es`.
- Columna lateral: tres segmentadores desplegables para
  `estado_ambiental_label_es`, `etapa` y `region`.

#### 2. Tiempos SEIA

- Fila superior: tarjetas `KPI expedientes admitidos`, `[Mediana meses]` y
  `[Tasa de desistimiento]`.
- Superior izquierda: gráfico de líneas KM con `agg_km[mes]` en X,
  `agg_km[prob_aprobado]` en Y y `agg_km[instrumento]` como leyenda; agregue
  `ic_inf` e `ic_sup` al tooltip. Formatee Y como porcentaje.
- Superior derecha: gráfico de líneas CIF con `agg_cif[mes]` en X,
  `agg_cif[incidencia]` en Y, `agg_cif[desenlace]` como leyenda y
  `agg_cif[instrumento]` en múltiplos pequeños. Formatee Y como porcentaje.
- Abajo: gráfico de líneas de cohorte con `agg_tendencia[anio_ingreso]` en X,
  `agg_tendencia[mediana_meses]` en Y y `agg_tendencia[instrumento]` como
  leyenda; `n` y `cohorte_incompleta` van al tooltip. Filtre o marque con línea
  discontinua las cohortes donde `cohorte_incompleta = TRUE`.
- Columna lateral: segmentadores de `fact_expedientes[instrumento]` y
  `fact_expedientes[segmento_inversion]`. Por diseño, afectan las tarjetas
  calculadas desde `fact_expedientes`; las tres curvas agregadas muestran la
  referencia poblacional completa mediante leyendas/múltiplos, pues `agg_*`
  no se relaciona.

#### 3. Expedientes

- Superior: segmentador de fecha tipo **Entre** usando `Calendario[Date]`, más
  segmentadores desplegables para `fact_expedientes[instrumento]`,
  `fact_expedientes[segmento_inversion]`, `fact_expedientes[region]` y
  `fact_expedientes[evento]`.
- Debajo: tarjetas `[N expedientes]`, `[Mediana meses]` y
  `[Tasa de desistimiento]`.
- Resto de la página: tabla de detalle con `exp_id`, `instrumento`, `region`,
  `macro_zona`, `tipologia`, `inversion_musd`, `segmento_inversion`,
  `fecha_ingreso`, `fecha_cierre`, `evento`, `duracion_dias`,
  `duracion_meses` y `en_cartera_cochilco`. No agregue nombres desde otras
  fuentes.

### Consistencia con el brief

Las tarjetas editoriales deben usar las medidas `KPI ...`, que consultan
`kpi_validados` por `claim_id`. El brief y el dashboard quedan así anclados al
mismo registro de claims `verificada`; sus KPIs deben coincidir exactamente.

---

## English

### Load and configuration

1. Run `make powerbi` and set the Power BI Desktop file locale to
   **Spanish (Chile) / `es-CL`**.
2. Use **Get data → Parquet** to load all six files from `data/powerbi/`. Keep
   the table names `fact_cartera`, `fact_expedientes`, `agg_km`, `agg_cif`,
   `agg_tendencia`, and `kpi_validados`.
3. Sort `fact_cartera[estado_ambiental_label_es]` by
   `fact_cartera[estado_ambiental_orden]`.
4. Do not add text columns from upstream artifacts. The export already removes
   holder/person names, RCA numbers, history, and long text.

The Parquet files encode dates as `date32` and declare every Arrow type
explicitly. Apply numeric formatting to measures, never to source columns.

### Relationships

Create only these relationships:

- `Calendario[Date]` 1→* `fact_expedientes[fecha_ingreso]`, active, with
  single-direction filtering from `Calendario`.
- `Calendario[Date]` 1→* `fact_cartera[fecha_ingreso]`, inactive, with
  single-direction filtering from `Calendario`.

Leave `agg_km`, `agg_cif`, `agg_tendencia`, and `kpi_validados` unrelated.
They contain pre-aggregated results or scalar values; relationships would alter
their meaning.

### Calendar and measures

Use the `Calendario` calculated table and all DAX measures in the Spanish
section above. They are ready for an `es-CL` file and use `;` as the argument
separator. If Desktop uses invariant DAX separators, replace `;` with commas.
Mark `Calendario` as the date table on `[Date]`, sort `[Mes]` by `[Mes número]`,
and apply each listed custom format through **Measure tools**. The measures
cover total and state investment, share of total, project and filing counts,
`MEDIANX` duration, withdrawal rate, and editorial KPIs retrieved with
`LOOKUPVALUE` by `claim_id`.

### Exact three-page layout

#### 1. Portfolio

- Top row: cards for portfolio investment, project count, investment without a
  filing while in study, and its share of total.
- Left: horizontal investment-by-environmental-status bars, with share of total
  in the tooltip.
- Right: descending clustered bars of total investment by region. Bars are
  specified instead of a map to avoid geocoding ambiguity.
- Bottom: project table with project, company, mine, region, stage, condition,
  commissioning range, investment, and environmental status.
- Side column: status, stage, and region slicers.

#### 2. SEIA timing

- Top row: admitted-filings, median-months, and withdrawal-rate cards.
- Upper left: KM line chart from `agg_km`, month on X, approval probability on
  Y, instrument as legend, and both confidence limits in the tooltip.
- Upper right: CIF line chart from `agg_cif`, month on X, incidence on Y,
  outcome as legend, and instrument as small multiples.
- Bottom: cohort trend from `agg_tendencia`, entry year on X, median months on
  Y, instrument as legend, with `n` and incomplete-cohort flag in the tooltip.
- Side column: instrument and investment-segment slicers from
  `fact_expedientes`. They filter fact-based cards; the unrelated aggregate
  curves remain full-population references split by legend/small multiples.

#### 3. Filings

- Top: a **Between** date slicer on `Calendario[Date]`, plus instrument,
  investment segment, region, and outcome slicers.
- Next row: filing-count, median-months, and withdrawal-rate cards.
- Remaining canvas: a filterable detail table with filing ID, instrument,
  region, macro zone, typology, investment, segment, entry/close dates,
  outcome, duration in days/months, and Cochilco-portfolio flag. Do not add
  names from upstream sources.

### Brief consistency

Editorial cards must use the `KPI ...` measures. Those measures retrieve only
verified values from `kpi_validados` by `claim_id`, so the dashboard and the
brief use the same source and their KPI values must match exactly.
