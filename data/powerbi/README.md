# Power BI exports / Exportaciones para Power BI

## Español

Ejecute `make powerbi` desde la raíz del repositorio para generar los seis
archivos Parquet de esta carpeta. Los `.parquet` son artefactos locales y están
ignorados por Git; este README es el único archivo versionado del directorio.

Cargue cada archivo en Power BI Desktop con **Obtener datos → Parquet** y
conserve el nombre del archivo como nombre de tabla. La configuración completa
de relaciones, medidas, formatos y páginas está en
[`docs/powerbi/model.md`](../../docs/powerbi/model.md).

## English

Run `make powerbi` from the repository root to generate the six Parquet files
in this directory. The `.parquet` files are local artifacts ignored by Git;
this README is the only versioned file in the directory.

Load every file in Power BI Desktop with **Get data → Parquet** and keep the
file name as the table name. The complete relationship, measure, formatting,
and page specification is in
[`docs/powerbi/model.md`](../../docs/powerbi/model.md).
