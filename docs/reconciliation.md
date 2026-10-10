# Cochilco Annex C reconciliation

CMIP preserves Table 1 exactly and reports control-table differences. It never
forces, reallocates, or scales project values to make a control total match.

## Portfolio total

Table 1 contains 59 physical rows totaling **104,549.2 MMUSD**, exactly equal
to the published portfolio total in Tables 4, 8, and 9.

## Table 4 — condition and mineral

All differences are confined to copper. The other mineral/condition cells
reconcile exactly.

| Condition | Table 1 (MMUSD) | Table 4 (MMUSD) | Table 1 − Table 4 |
|---|---:|---:|---:|
| Base | 46,509.1 | 42,831.1 | +3,678.0 |
| Probable | 10,300.1 | 6,593.9 | +3,706.2 |
| Posible | 9,591.0 | 13,297.2 | −3,706.2 |
| Potencial | 38,149.0 | 41,827.0 | −3,678.0 |

The differences are symmetric reclassifications: the Base/Potencial pair nets
to zero, as does the Probable/Posible pair. The most probable cause is that the
controls decompose or reclassify underlying Codelco investments while Table 1
assigns one condition to each displayed aggregate row. Annex C explicitly says
that Chuquicamata Subterránea represents three projects, Nuevo Nivel Mina three,
and Súlfuros RT Fase II two; Table 1 also has generic Codelco program rows for
Otros Proyectos de Desarrollo and Tranques. Because the overall and
mineral-level totals agree exactly, this is not treated as missing investment.
Pre-2025 investment allocation may contribute to the control methodology, but
the workbook does not provide enough row-level detail to prove a single cause.

The raw Annex C CSV and workbook were also compared row by row with the parsed
`condicion` field. All 59 strings and investments are identical after parsing;
there are no misparsed rows. Therefore the published rounded shares (41%, 6%,
13%, and 40%) use Table 4's 64-project control basis rather than the literal
59 displayed rows in Table 1 (44.5%, 9.9%, 9.2%, and 36.5%).

## Table 5 — project type

The raw and parsed `Tipo de Proyecto` values also agree for every displayed
row. Table 1 produces Reposición 50.3%, Expansión 30.2%, and Nuevo 19.5%.
Table 5 reports 46.7%, 33.7%, and 19.5% (rounded in the publication to 47%,
34%, and 20%). The 3,706.2 MMUSD excess in Table 1 Reposición is offset by the
same shortfall in Expansión (rounding accounts for 0.04 MMUSD). This is the
same magnitude as the Probable/Posible reclassification in Table 4 and is
consistent with the control tables decomposing or reclassifying aggregate
Codelco rows. No CMIP values are forced to the controls.

## Project count

Table 1 has **59 displayed rows** while Tables 4 and 8 report **64 projects**.
The five-project difference is fully explained by the three footnoted aggregate
rows: 3 underlying Chuquicamata projects, 3 Nuevo Nivel Mina projects, and 2
Súlfuros RT projects are represented by 3 displayed rows (8 − 3 = 5). CMIP
keeps the 59 source rows and flags these aggregates rather than fabricating
component records.

## Table 8 — region

Every Table 1 regional investment total, including the explicit `Varias`
category, agrees with Table 8. The portfolio totals are **104,549.2 MMUSD** in
both tables.

## Table 10 — temporal distribution

The seven published period buckets total **104,549.1 MMUSD**, which is
**0.1 MMUSD below** Table 1. This is a control-table rounding difference: each
period is published to one decimal place. No project value is adjusted.
