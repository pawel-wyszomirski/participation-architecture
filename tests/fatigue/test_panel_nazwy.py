# catalog-read
"""One name per component, everywhere the reader can see it.

Why this exists (2026-08-07, pilot session P04): the panel showed the formula with
internal keys - `DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness + …)` - and,
directly underneath, a table of weights using reader-facing labels ("Activity spike").
The participant had to ask whether the two referred to the same thing:

    "which here is the weight for burstiness. Is this the activity spike?"

That question costs the study twice. It spends the participant's attention on naming
while we are measuring their cognitive load, and it lands in the field notes as
"did not understand the component" when the truth is "did not recognise the name".

These are static checks: they read the config and the page, so they run without a
browser and without a server. They fail when a component is added to the index and
its label is forgotten - which is exactly when the mismatch would come back.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "app" / "static" / "dashboard.html"
CONFIG = ROOT / "fatigue_config.yaml"
ENGINE = ROOT / "app" / "services" / "fatigue_engine.py"


def _weight_rows() -> dict:
    """The key → label mapping the page uses for the weights table."""
    html = DASHBOARD.read_text(encoding="utf-8")
    blok = re.search(r"const WEIGHT_ROWS = \[(.*?)\];", html, re.S)
    assert blok, "WEIGHT_ROWS disappeared from the dashboard"
    return dict(re.findall(r'\["(\w+)",\s*"([^"]+)"\]', blok.group(1)))


def test_every_weighted_component_has_a_label():
    """A component with a weight but no label would show up as a bare key."""
    wagi = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["weights"]
    etykiety = _weight_rows()
    brakujace = sorted(set(wagi) - set(etykiety))
    assert not brakujace, f"components without a reader-facing label: {brakujace}"


def test_formula_is_translated_before_it_is_shown():
    """The page must render the formula through the label mapping, not raw."""
    html = DASHBOARD.read_text(encoding="utf-8")
    assert "function formulaWithLabels" in html, "the translation helper is gone"
    assert re.search(r'class:\s*"dfi-formula",\s*text:\s*formulaWithLabels\(', html), (
        "the formula is rendered raw again - internal keys will reach the reader"
    )


def test_translation_leaves_no_internal_key_behind():
    """Run the same substitution the page runs, on the formula the engine sends."""
    wzor = re.search(r'"(DFI = \(.*?)"\s*\n?\s*"(.*?)"', ENGINE.read_text(encoding="utf-8"), re.S)
    formula = (wzor.group(1) + wzor.group(2)) if wzor else ""
    assert "DFI =" in formula, "could not read the formula from the engine"

    etykiety = _weight_rows()
    przetlumaczona = formula
    for klucz, etykieta in etykiety.items():
        przetlumaczona = przetlumaczona.replace(klucz, etykieta)

    # A key counts as leftover only when it stands on its own - "volume" inside
    # "Recent volume" is the substitution working, not failing.
    for klucz, etykieta in etykiety.items():
        bez_etykiet = przetlumaczona.replace(etykieta, "")
        assert not re.search(rf"\b{re.escape(klucz)}\b", bez_etykiet), (
            f"internal key '{klucz}' survives in the formula shown to the reader"
        )


def test_labels_are_not_internal_keys():
    """A label identical to the key means the rename never happened."""
    for klucz, etykieta in _weight_rows().items():
        assert etykieta != klucz, f"'{klucz}' is shown under its internal name"
