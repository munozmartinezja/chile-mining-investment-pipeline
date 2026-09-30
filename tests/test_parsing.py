from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from cmip.extract.cochilco import extract_table, write_interim_tables
from cmip.validate import parse_chilean_number, parse_puesta_en_marcha, project_slug


class ParsingTests(unittest.TestCase):
    def test_chilean_number_parser_handles_thousands_and_decimal_separators(self) -> None:
        self.assertEqual(parse_chilean_number("104.549,2"), 104_549.2)
        self.assertEqual(parse_chilean_number("987"), 987.0)

    def test_puesta_en_marcha_parser_handles_range_and_single_year(self) -> None:
        self.assertEqual(parse_puesta_en_marcha("2025-2029"), (2025, 2029))
        self.assertEqual(parse_puesta_en_marcha("2027"), (2027, 2027))

    def test_header_and_footnote_detection(self) -> None:
        sheet = pd.DataFrame(
            [
                [None, None, None],
                [None, "Tabla 1: Catastro", None],
                [None, None, None],
                [None, "Empresa", "Inversión [MMUS$]"],
                [None, "Codelco", "1.000,0"],
                [None, "(1) Nota", None],
                [None, "Ignored", "2.000,0"],
            ]
        )

        result = extract_table(sheet, title_row=1)

        self.assertEqual(result.columns.tolist(), ["Empresa", "Inversión [MMUS$]"])
        self.assertEqual(
            result.to_dict("records"),
            [{"Empresa": "Codelco", "Inversión [MMUS$]": "1.000,0"}],
        )

    def test_project_slug_removes_accents_and_normalizes_spaces(self) -> None:
        self.assertEqual(
            project_slug("Compañía Minera", "Proyecto Súlfuros RT"),
            "compania-minera-proyecto-sulfuros-rt",
        )

    def test_interim_writer_handles_mixed_excel_year_types(self) -> None:
        table = pd.DataFrame({"Puesta en Marcha": [2025, "2025-2029"]})
        with TemporaryDirectory() as directory:
            outputs = write_interim_tables({1: table}, Path(directory))
            saved = pd.read_parquet(outputs[1])
        self.assertEqual(saved["Puesta en Marcha"].tolist(), ["2025", "2025-2029"])

    def test_populated_column_with_blank_header_is_retained(self) -> None:
        sheet = pd.DataFrame(
            [
                ["Tabla 4: Control", None, None],
                ["Condición", "Total", None],
                ["Base", "42.831,1", "41,0%"],
                ["Fuente: Cochilco", None, None],
            ]
        )

        result = extract_table(sheet, title_row=0)

        self.assertEqual(result.columns.tolist(), ["Condición", "Total", "unnamed_3"])
        self.assertEqual(result.iloc[0]["unnamed_3"], "41,0%")


if __name__ == "__main__":
    unittest.main()
