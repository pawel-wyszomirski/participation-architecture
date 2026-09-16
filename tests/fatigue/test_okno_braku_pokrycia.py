# <!-- catalog-read --> sprawdzone: tests/fatigue/ nie ma pliku o zakresie pokrycia zrodel
"""Brak okna glosowania SPOZA okna wyniku nie dyskwalifikuje pomiaru (16.09, D1=C).

Druga odslona tej samej klasy, co zakres bramki powiazania etapow naprawiony tego samego
dnia rano. Zglosil Pawel: pomiar odrzucany z powodu niepelnosci, ktora nie moze zmienic
zadnej liczby wchodzacej do wyniku.

Okna glosowan z HISTORII delegata nie wchodza do zadnego skladnika: `concurrent_active`
liczy sie z `ecosystem_proposals` (osobne zrodlo ekspozycji), a `volume` i `burstiness`
licza DATY glosow w oknie 7 i 30 dni. Przypadek zrodlowy: pomiar Manu blokowal jeden glos
z 2026-05-20, 117 dni przed mierzona chwila, ktorego propozycja powstala trzy dni przed
granica 120-dniowego skanu zdarzen.

Warunek jest CELOWO waski - testy nizej pilnuja kazdego jego czlonu osobno.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import FatigueEngine  # noqa: E402

TERAZ = int(time.time())
DZIEN = 86_400


@pytest.fixture
def silnik():
    return FatigueEngine()


def pokwitowanie(**nadpisz):
    """Pokwitowanie governora z brakiem okna - domyslnie SPOZA okna wyniku."""
    baza = {
        "source": "governor", "state": "PARTIAL",
        "availability_state": "HEALTHY", "coverage_state": "PARTIAL_DATA",
        "events": 4, "record_count": 4, "unknown_window": 1,
        "unknown_window_newest_at": TERAZ - 117 * DZIEN,
        "limit_hit": False, "detail": "1 of 4 votes without a known voting window",
    }
    baza.update(nadpisz)
    return baza


def powody(silnik, receipt):
    """Same powody dyskwalifikujace, bez notatek."""
    _, reasons, notes = silnik._eligibility(
        [receipt], "ecosystem:snapshot+governor", TERAZ,
        ekspozycja_pusta=False, cel_kontraktowy=True,
        podstawy_bez_dowodu=[], okna_bez_dowodu=[],
        novelty_basis="", taxonomy_snapshot_id="tax:x")
    return reasons, notes


def test_brak_okna_sprzed_117_dni_nie_dyskwalifikuje(silnik):
    """Przypadek Manu: glos spoza okna wyniku wchodzi do NOTATEK, nie do powodow."""
    reasons, notes = powody(silnik, pokwitowanie())
    assert not any("governor" in r and "coverage" in r for r in reasons), (
        f"brak okna spoza okna wyniku nie ma prawa dyskwalifikowac: {reasons}")
    assert any("cannot change any of them" in n for n in notes), (
        f"fakt ma zostac zapisany jako notatka: {notes}")


def test_brak_okna_W_oknie_wyniku_nadal_dyskwalifikuje(silnik):
    """To nie jest zdjecie bramki - swiezy brak okna dziala jak przedtem."""
    reasons, _ = powody(silnik, pokwitowanie(unknown_window_newest_at=TERAZ - 3 * DZIEN))
    assert any("governor" in r and "coverage" in r for r in reasons), (
        f"brak okna W oknie wyniku ma dyskwalifikowac: {reasons}")


def test_luka_w_skanie_dyskwalifikuje_mimo_starego_znacznika(silnik):
    """`limit_hit` znaczy takze 'okno skanu nie zwrocilo wyniku' - to luka innej klasy.

    Kawalek historii nieobejrzany nie jest tym samym, co obejrzany rekord bez jednego pola.
    """
    reasons, _ = powody(silnik, pokwitowanie(limit_hit=True))
    assert any("governor" in r and "coverage" in r for r in reasons), (
        f"luka w pokryciu skanu ma dyskwalifikowac: {reasons}")


def test_brak_znacznika_nie_przepuszcza(silnik):
    """None znaczy 'nie mierzono' - nie jest dowodem, ze wszystkie okna sa znane."""
    reasons, _ = powody(silnik, pokwitowanie(unknown_window_newest_at=None))
    assert any("governor" in r and "coverage" in r for r in reasons), (
        f"brak pomiaru nie jest dowodem kompletnosci: {reasons}")


def test_inne_pokrycie_niz_PARTIAL_DATA_nie_przepuszcza(silnik):
    """Furtka dotyczy WYLACZNIE brakujacych pol, nie kazdego niepelnego pokrycia."""
    reasons, _ = powody(silnik, pokwitowanie(coverage_state="TRUNCATED", state="TRUNCATED"))
    assert any("governor" in r and "coverage" in r for r in reasons), (
        f"obciety zbior to inna klasa niz brakujace okno: {reasons}")
