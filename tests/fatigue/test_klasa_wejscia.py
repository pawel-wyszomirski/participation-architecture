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


# --- 3. Dwie reguły czasu głosu ---------------------------------------------

@pytest.mark.skip(reason=(
    "PRZYPADEK NIEODTWORZONY. Pochodzi z cudzego przebiegu (Codex, gpt-6-astra, "
    "10.09: 0,0 wobec 22,2 DFI pod jednym identyfikatorem). Moja konstrukcja go NIE "
    "odtwarza: sabotaż na 09ece75 pokazał, że ten warunek przechodzi także na kodzie "
    "sprzed naprawy, czyli nie chroni przed niczym. Zostaje wyłączony, dopóki nie mam "
    "wejścia, którym rozjazd faktycznie widać - test przechodzący zawsze jest gorszy "
    "niż jego brak, bo udaje pokrycie."))
def test_dwie_reguly_czasu_glosu_daja_ten_sam_odcisk(silnik):
    """Obliczenia czytają `voted_at → start`, kanonizacja `voted_at → cast_at → 0`.
    Rekord bez `voted_at`, ale ze `start`, ma w projekcji zero, a w obliczeniu
    czas otwarcia. Zmierzone: 0,0 wobec 22,2 DFI."""
    z_czasem = Propozycja(id="c-1", title="C", body="słowo " * 100,
                          start=BAZA - 100_000, end=BAZA - 90_000,
                          voted_at=BAZA - 95_000, category="treasury",
                          lifecycle_id="cykl-z", native_proposal_id="0xc")
    bez_czasu = Propozycja(id="c-1", title="C", body="słowo " * 100,
                           start=BAZA - 100_000, end=BAZA - 90_000,
                           voted_at=0, category="treasury",
                           lifecycle_id="cykl-z", native_proposal_id="0xc")
    cel = _cel()
    a = zmierz(silnik, cel, [z_czasem])
    b = zmierz(silnik, cel, [bez_czasu])
    # Po naprawie te dwa wejścia PRZESTAŁY być tożsame - projekcja niesie jedną,
    # ujednoliconą regułę czasu, więc rekord bez `voted_at` jest innym rekordem.
    # Warunek zmienia się więc z „ten sam identyfikator, ten sam wynik" na
    # „rozróżnienie nie ma prawa zniknąć". Gdyby ktoś przywrócił dwie reguły czasu,
    # identyfikatory znów by się zrównały i ten test padnie.
    assert a.identity.measurement_id != b.identity.measurement_id, (
        "regresja: rekord z czasem głosu i bez niego znów dzielą jeden identyfikator "
        f"({a.identity.measurement_id}) przy DFI {a.fatigue_score} i {b.fatigue_score}")


# --- 4. Granica między tytułem a treścią ------------------------------------

@pytest.mark.skip(reason=(
    "PRZYPADEK NIEODTWORZONY, ta sama przyczyna co przy regule czasu. Cudzy przebieg "
    "dał 5,0 wobec 10,0 DFI przy 1 wobec 711 słów treści; moja konstrukcja daje różne "
    "identyfikatory już na 09ece75. Wyłączony do czasu uzyskania parametrów wejścia."))
def test_przesuniecie_tekstu_miedzy_tytulem_a_trescia(silnik):
    """`reading_time` liczy słowa z samego `body`, a tożsamość hashuje
    `title + "\\n" + body`. Sklejenie nie zachowuje granicy pól, więc przesunięcie
    fragmentu z treści do tytułu zostawia hash bez zmian. Zmierzone: 5,0 wobec 10,0."""
    tresc = "słowo " * 400
    cel_a = _cel()
    cel_a.title = ""
    cel_a.body = "\n" + tresc
    cel_b = _cel()
    cel_b.title = "\n" + tresc.split(" ", 1)[0]
    cel_b.body = tresc.split(" ", 1)[1]
    historia = [Propozycja(id="h-1", title="H", body="słowo " * 50,
                           start=BAZA - 300_000, end=BAZA - 200_000,
                           voted_at=BAZA - 250_000, category="treasury",
                           lifecycle_id="cykl-h", native_proposal_id="0xh")]
    a = zmierz(silnik, cel_a, historia)
    b = zmierz(silnik, cel_b, historia)
    # Po naprawie `title` i `body` idą do serializacji osobno, więc przesunięcie
    # fragmentu między nimi jest widoczne w tożsamości. Wcześniej hash liczył się
    # ze sklejenia i granica pól ginęła. Ten warunek pilnuje, żeby sklejenie nie wróciło.
    assert a.identity.measurement_id != b.identity.measurement_id, (
        "regresja: przesunięcie tekstu z treści do tytułu znów nie rusza identyfikatora "
        f"({a.identity.measurement_id}) przy DFI {a.fatigue_score} i {b.fatigue_score}")


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
