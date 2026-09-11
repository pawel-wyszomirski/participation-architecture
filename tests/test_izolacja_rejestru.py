"""Przebieg testowy nie ma prawa dopisać wiersza do rejestru manifestów badania.

POWÓD (11.09.2026, pomiar przy wdrożeniu 1.8.0)
-----------------------------------------------
`data/manifests/pomiary-2026-09.jsonl` w HEAD miał dwadzieścia wpisów. Wszystkie
niosły JEDEN `vote_event_id` (syntetyczny głos z atrap) i różne `code_commit` -
czyli po dwa wiersze na każdy przebieg pytest z ostatnich dni. Ani jeden nie
opisywał pomiaru, który naprawdę się odbył.

To groźniejsze niż śmieć w repozytorium: manifest jest ŚCIEŻKĄ AUDYTU rozdziału
Methods - odpowiada na pytanie, który wynik powstał na której wersji narzędzia.
Wiersz z przebiegu testowego ma identyczny format co prawdziwy, więc w dowodzie
niczym się od niego nie różni.

`tests/conftest.py` izolował bazę od 09.09 z dokładnie tego samego powodu
(`DATABASE_URL` na tymczasowy SQLite) i pomijał drugą składnicę stanu.
**Izolacja jednego składu nie jest izolacją stanu** - stąd ten strażnik pyta
o KATALOG, nie o konkretny plik: kolejny rejestr dołożony obok objęty jest
pomiarem, gdy tylko zacznie korzystać z tej samej ścieżki.

Uruchomienie: python3 -m pytest tests/test_izolacja_rejestru.py -q
"""
import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services import fatigue_engine  # noqa: E402

REPO = Path(ROOT).resolve()
REJESTR_REPO = REPO / "data" / "manifests"


def test_katalog_manifestow_nie_wskazuje_na_repozytorium():
    """Gdyby wskazywał, każdy przebieg pytest dopisywałby do śladu audytu."""
    katalog = Path(fatigue_engine.KATALOG_MANIFESTOW).resolve()
    assert katalog != REJESTR_REPO, (
        "rejestr manifestów badania jest celem zapisu w przebiegu testowym - "
        "ustaw PA_KATALOG_MANIFESTOW w tests/conftest.py PRZED importem app.*"
    )
    assert REPO not in katalog.parents and katalog != REPO, (
        f"katalog manifestów ({katalog}) leży w drzewie repozytorium"
    )


def test_zapis_ladujE_w_katalogu_testowym_a_nie_w_repo(tmp_path):
    """Dowód zachowaniem, nie deklaracją: po zapisie rejestr w repo ma tyle samo
    wierszy co przed, a plik tymczasowy - o jeden więcej."""
    przed = {}
    if REJESTR_REPO.exists():
        przed = {p: p.read_bytes() for p in REJESTR_REPO.glob("*.jsonl")}

    wynik = fatigue_engine.dopisz_manifest(
        {"measurement_id": "test-izolacji", "computed_at": "2026-09-11T23:00:00+00:00"},
    )
    assert wynik in (
        fatigue_engine.MANIFEST_ZAPISANY,
        fatigue_engine.MANIFEST_JUZ_BYL,
    ), wynik

    po = {}
    if REJESTR_REPO.exists():
        po = {p: p.read_bytes() for p in REJESTR_REPO.glob("*.jsonl")}
    assert po == przed, (
        "przebieg testowy zmienił rejestr manifestów w repozytorium: "
        f"{sorted({p.name for p in set(po) ^ set(przed)})}"
    )

    docelowy = Path(fatigue_engine.KATALOG_MANIFESTOW)
    zapisane = "".join(p.read_text(encoding="utf-8") for p in docelowy.glob("*.jsonl"))
    assert "test-izolacji" in zapisane, (
        "wiersz nie trafił nigdzie - zapis milczy zamiast pisać do katalogu testowego"
    )
