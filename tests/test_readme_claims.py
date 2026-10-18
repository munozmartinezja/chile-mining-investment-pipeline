"""Guard: formatted figures in README.md must match the verified claims register.

If a claim value changes in the register, this test will fail until README.md
is updated to reflect the new figure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

_REQUIRED_DATA = [
    ROOT / "data/processed/cochilco_seia.parquet",
    ROOT / "data/processed/survival_km_summary.parquet",
    ROOT / "data/processed/survival_competing_risks_summary.parquet",
    ROOT / "data/interim/sea_mining.parquet",
]
requires_local_data = pytest.mark.skipif(
    not all(p.exists() for p in _REQUIRED_DATA),
    reason="requires local portfolio and SEA analysis parquets",
)


def _fmt_pct(v: float, *, es: bool) -> str:
    sep = "," if es else "."
    return f"{v:.1f}".replace(".", sep) + "%"


def _fmt_mmus_es(v: float) -> str:
    rounded = int(round(v))
    return f"{rounded:,}".replace(",", ".") + " MMUS$"


def _get(reg, claim_id: str) -> float:
    rows = reg[reg["claim_id"] == claim_id]
    assert not rows.empty, f"claim_id {claim_id!r} not found in register"
    return float(rows.iloc[0]["valor"])


@pytest.fixture(scope="module")
def register():
    from cmip.validation import build_claims_register

    return build_claims_register()


@pytest.fixture(scope="module")
def readme_text():
    return README.read_text(encoding="utf-8")


# Each entry: (claim_id, formatter, description)
_CHECKS: list[tuple[str, object, str]] = [
    ("estado_sin_expediente_en_estudio_pct", lambda v: _fmt_pct(v, es=True), "sin_exp_pct ES"),
    ("estado_sin_expediente_en_estudio_pct", lambda v: _fmt_pct(v, es=False), "sin_exp_pct EN"),
    ("estado_sin_expediente_en_estudio_inversion", _fmt_mmus_es, "sin_exp_inv ES"),
    ("aj_EIA_aprobado_24m", lambda v: _fmt_pct(v, es=True), "aj_eia_24m ES"),
    ("aj_EIA_aprobado_24m", lambda v: _fmt_pct(v, es=False), "aj_eia_24m EN"),
    ("aj_EIA_aprobado_36m", lambda v: _fmt_pct(v, es=True), "aj_eia_36m ES"),
    ("aj_EIA_aprobado_36m", lambda v: _fmt_pct(v, es=False), "aj_eia_36m EN"),
    ("km_EIA_aprobado_24m", lambda v: _fmt_pct(v, es=True), "km_eia_24m ES"),
    ("km_EIA_aprobado_24m", lambda v: _fmt_pct(v, es=False), "km_eia_24m EN"),
    ("km_aj_brecha_EIA_24m_pp", lambda v: _fmt_pct(v, es=True).replace("%", " pp"), "brecha_pp ES"),  # noqa: E501
    ("km_aj_brecha_EIA_24m_pp", lambda v: _fmt_pct(v, es=False).replace("%", " pp"), "brecha_pp EN"),  # noqa: E501
    ("eia_100m_aj_aprobado_24m_estimacion", lambda v: _fmt_pct(v, es=True), "eia100_est ES"),
    ("eia_100m_aj_aprobado_24m_estimacion", lambda v: _fmt_pct(v, es=False), "eia100_est EN"),
    ("eia_100m_aj_aprobado_24m_ic95_inf", lambda v: _fmt_pct(v, es=True), "eia100_ci_lo ES"),
    ("eia_100m_aj_aprobado_24m_ic95_sup", lambda v: _fmt_pct(v, es=True), "eia100_ci_hi ES"),
    ("eia_100m_aj_aprobado_24m_ic95_inf", lambda v: _fmt_pct(v, es=False), "eia100_ci_lo EN"),
    ("eia_100m_aj_aprobado_24m_ic95_sup", lambda v: _fmt_pct(v, es=False), "eia100_ci_hi EN"),
    ("estado_en_evaluacion_inversion", _fmt_mmus_es, "en_eval_inv ES"),
    ("estado_aprobado_inversion", _fmt_mmus_es, "aprobado_inv ES"),
    ("estado_aprobado_pct", lambda v: _fmt_pct(v, es=True), "aprobado_pct ES"),
    ("estado_aprobado_pct", lambda v: _fmt_pct(v, es=False), "aprobado_pct EN"),
]


@requires_local_data
@pytest.mark.parametrize("claim_id,fmt,desc", _CHECKS, ids=[d for _, _, d in _CHECKS])
def test_readme_claim_present(claim_id, fmt, desc, register, readme_text):
    val = _get(register, claim_id)
    formatted = fmt(val)
    assert formatted in readme_text, (
        f"[{desc}] Claim {claim_id!r} formatted as {formatted!r} not found in README.md. "
        f"Register value: {val}"
    )


def test_readme_relative_links_exist() -> None:
    import re
    import subprocess

    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    text = README.read_text(encoding="utf-8")
    pattern = re.compile(r"(?:!\[[^\]]*\]|(?<!!)\[[^\]]*\])\(([^)#]+?)(?:#[^)]*)?\)")
    missing: list[str] = []
    for match in pattern.finditer(text):
        href = match.group(1).strip()
        if href.startswith("http://") or href.startswith("https://"):
            continue
        if href not in tracked:
            missing.append(href)

    assert missing == [], f"README.md links/images pointing to untracked paths: {missing}"


def test_powerbi_readme_relative_links_exist() -> None:
    import re
    import subprocess

    powerbi_readme = ROOT / "data" / "powerbi" / "README.md"
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    text = powerbi_readme.read_text(encoding="utf-8")
    pattern = re.compile(r"(?:!\[[^\]]*\]|(?<!!)\[[^\]]*\])\(([^)#]+?)(?:#[^)]*)?\)")
    missing: list[str] = []
    for match in pattern.finditer(text):
        href = match.group(1).strip()
        if href.startswith("http://") or href.startswith("https://"):
            continue
        # resolve relative to data/powerbi/
        resolved = (ROOT / "data" / "powerbi" / href).resolve().relative_to(ROOT.resolve())
        resolved_str = str(resolved)
        if resolved_str not in tracked:
            missing.append(href)

    assert missing == [], (
        f"data/powerbi/README.md links/images pointing to untracked paths: {missing}"
    )
