"""Składniki i tożsamość muszą czytać JEDNO wejście.

<!-- catalog-read --> Nowy plik obok istniejących w tests/fatigue: sprawdzono, że
`test_measurement_identity.py` pilnuje kierunku odwrotnego, a pozostałe pliki
(`test_per_event`, `test_closure_review`, `test_ekspozycja_ekosystemu`,
`test_merge_stages`) nie zawierają warunku permutacji wejścia.

Dotychczasowy `test_measurement_identity.py` sprawdza kierunek: różne wartości
muszą dać różny identyfikator. Ten plik sprawdza kierunek odwrotny i trudniejszy:
**ten sam identyfikator musi znaczyć ten sam wynik**.

Cztery przypadki niżej to wykonane kontrprzykłady z 2026-09-10, nie hipotezy.
Wspólna przyczyna: obliczenie i tożsamość czytają dane w dwóch różnych
reprezentacjach, więc różnica widoczna dla jednej strony bywa niewidoczna dla
drugiej. Każdy z nich pada na `09ece75`.

Piąty przypadek, jeszcze nieznany, ma wyłapać `test_permutacja_nie_rusza_wyniku`
- jedyny test w tym pliku, który nie opisuje konkretnej usterki, tylko własność.
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.fatigue_engine import FatigueEngine  # noqa: E402


@dataclass
class Propozycja:
    id: str
    title: str = ""
    body: str = ""
    start: int = 0
    end: int = 0
    voted_at: int = 0
    created_at: int = 0
    category: Optional[str] = None
    native_proposal_id: str = ""
    source_domain: str = "snapshot"
    lifecycle_id: str = ""
    stage_ids: List[str] = field(default_factory=list)


BAZA = 1_780_000_000


@pytest.fixture
def silnik():
    return FatigueEngine()


def _pokwitowania(ile):
    p = [{"source": s, "state": "HEALTHY_COMPLETE", "events": ile}
         for s in ("snapshot", "governor", "taxonomy")]
    p.append({"source": "ecosystem", "state": "HEALTHY_COMPLETE", "events": 1})
    return p


#: Wartownik odróżnia „nie podano" od „podano brak ekspozycji". Bez niego
#: `ekosystem=None` cicho zamieniało się w domyślną listę i przypadek 2 przechodził
#: mimo nienaprawionego kodu - czyli test mierzył co innego, niż deklarował.
BRAK = object()


def zmierz(silnik, cel, historia, ekosystem=BRAK):
    eko = ([Propozycja(id="eco-1", start=0, end=2_000_000_000)]
           if ekosystem is BRAK else ekosystem)
    return silnik.compute_per_event(
        address="0xTEST",
        target_proposal=cel,
        voted_history=list(historia) + [cel],
        now=datetime.fromtimestamp(cel.voted_at or BAZA, timezone.utc),
        ecosystem_proposals=eko,
        source_receipts=_pokwitowania(len(historia)),
    )


def _cel(kategoria="treasury"):
    return Propozycja(
        id="prop-target", title="Authorize PGA", body="treść " * 300,
        start=BAZA - 600_000, end=BAZA + 100, voted_at=BAZA,
        created_at=BAZA - 700_000, category=kategoria,
        native_proposal_id="0xtarget", lifecycle_id="cykl-celu",
    )


def _porownaj(a, b, co):
    """Ten sam identyfikator = ten sam wynik. Inaczej to kolizja, nie zaokrąglenie."""
    if a.identity.measurement_id != b.identity.measurement_id:
        pytest.fail(
            f"{co}: identyfikatory się różnią, więc ten test nie sprawdza już kolizji "
            "- popraw przypadek, zamiast go usuwać")
    assert a.fatigue_score == b.fatigue_score, (
        f"{co}: DFI {a.fatigue_score} wobec {b.fatigue_score} pod jednym "
        f"{a.identity.measurement_id}")


# --- 1. Kolejność etapów jednego cyklu o różnych kategoriach ----------------

def test_kolejnosc_etapow_nie_rusza_kategorii_cyklu(silnik):
    """`_novelty_per_event` bierze PIERWSZĄ napotkaną kategorię cyklu, a tożsamość
    liczy się z historii posortowanej po `id`. Zmierzone: novelty 0,0 wobec 1,0."""
    a = Propozycja(id="a-etap", title="Stage A", body="słowo " * 200,
                   start=BAZA - 200_000, end=BAZA - 100_000, voted_at=BAZA - 150_000,
                   category="treasury", lifecycle_id="cykl-x", native_proposal_id="0xa")
    b = Propozycja(id="b-etap", title="Stage B", body="słowo " * 200,
                   start=BAZA - 200_000, end=BAZA - 100_000, voted_at=BAZA - 150_000,
                   category="protocol", lifecycle_id="cykl-x", native_proposal_id="0xb")
    cel = _cel("treasury")
    _porownaj(zmierz(silnik, cel, [a, b]), zmierz(silnik, cel, [b, a]),
              "kolejność etapów jednego cyklu")


# --- 2. Równy czas głosu, różne okna ----------------------------------------

def test_rowny_czas_glosu_rozne_okna_nie_rusza_wyniku(silnik):
    """`_decision_representatives` przy jednakowym czasie wybiera pierwszy etap
    z kolejności wejściowej. Zmierzone: 22,2 wobec 28,4 DFI."""
    a = Propozycja(id="a-okno", title="A", body="słowo " * 100,
                   start=BAZA - 900_000, end=BAZA - 10, voted_at=BAZA - 100_000,
                   category="treasury", lifecycle_id="cykl-y", native_proposal_id="0xa")
    b = Propozycja(id="b-okno", title="B", body="słowo " * 100,
                   start=BAZA - 50_000, end=BAZA - 40_000, voted_at=BAZA - 100_000,
                   category="treasury", lifecycle_id="cykl-y", native_proposal_id="0xb")
    cel = _cel()
    # Bez ekspozycji ekosystemu składnik concurrency schodzi na okna etapów, więc
    # wybór reprezentanta widać w wyniku. Przy dostępnej ekspozycji ta sama różnica
    # zostaje w metryce `voted_concurrent` i nie rusza DFI.
    _porownaj(zmierz(silnik, cel, [a, b], ekosystem=None),
              zmierz(silnik, cel, [b, a], ekosystem=None),
              "równy czas głosu, różne okna")


# --- 4. Granica między tytułem a treścią ------------------------------------


# Przypadki „dwie reguły czasu głosu" i „granica między tytułem a treścią" NIE stoją
# w tym pliku. Moje konstrukcje ich nie odtwarzały - przechodziły również na kodzie
# sprzed naprawy, co wykrył sabotaż w osobnym drzewie roboczym. Poprawne wersje, z polem
# `cast_at` i bez dopisywania celu do historii, leżą w `test_odtworzenie_wejscia.py`
# (`test_czas_rozne_znaczenie_rozne_id`, `test_tekst_granica_pol_rozne_id`) i tam padają
# na starym silniku. Trzymanie tu drugiej, słabszej kopii dawałoby złudzenie pokrycia.

# --- 5. Własność, nie usterka: dowolna permutacja ----------------------------

@pytest.mark.parametrize("ziarno", [1, 2, 3, 5, 8, 13])
def test_permutacja_nie_rusza_wyniku(silnik, ziarno):
    """Jedyny test w tym pliku, który nie opisuje znanego przypadku.

    Kolejność rekordów w odpowiedzi źródła jest własnością transportu. Jeśli
    zmienia wynik, to składnik czyta coś, czego tożsamość nie widzi - niezależnie
    od tego, czy wiemy dziś, który to składnik. Ten warunek ma wyłapać piątą
    rozbieżność, o której nikt jeszcze nie wie.
    """
    import random

    historia = [
        Propozycja(id=f"p-{i}", title=f"T{i}", body="słowo " * (50 + i * 7),
                   start=BAZA - (i + 1) * 90_000, end=BAZA - (i + 1) * 80_000,
                   voted_at=BAZA - (i + 1) * 85_000,
                   category=["treasury", "protocol", "grants", None][i % 4],
                   lifecycle_id=f"cykl-{i // 2}", native_proposal_id=f"0x{i:04x}")
        for i in range(8)
    ]
    cel = _cel()
    wzorzec = zmierz(silnik, cel, historia)

    pomieszana = list(historia)
    random.Random(ziarno).shuffle(pomieszana)
    inna = zmierz(silnik, cel, pomieszana)

    _porownaj(wzorzec, inna, f"permutacja historii (ziarno {ziarno})")
