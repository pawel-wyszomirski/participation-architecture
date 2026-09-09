"""
The measurement identity contract: the same measurement_id must mean the same
canonical result.

These conditions were written BEFORE the I1-I3 repair of 2026-09-09, as the
passing criteria for it (ANALIZA-2026-09-09-sciezki-zapasowe.md, section 10),
and they lived in pa/analiza/test-bramka-integralnosci.py while the engine was
frozen. They are regression now, not a one-off: the defect they describe is
invisible in the data - two runs return a number each, both plausible, under
one identifier.

What the counterexample showed: changing only the VALUE of `category` in the
history, with every record identifier untouched, moved the score from 44.90 to
46.60 while measurement_id stayed 83df5f4f2301ef52b6b98551f1ae9bea. The manifest
hashed sets of record ids, the target body, the receipts and the verdict - not
the values the result is a function of.

I2 (a repeated registration returns the stored row, never a fresh recompute) is
not here: it needs the API and a database, and it is covered by
tests/test_api_per_event.py.

Run with: pytest tests/fatigue/test_measurement_identity.py -v
"""

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import FatigueEngine


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


def zbuduj(kategorie_historii, kategoria_celu="treasury", domena="snapshot"):
    """Cel i historia o STAŁYCH identyfikatorach - zmienne są tylko wartości kategorii."""
    cel = Propozycja(
        id="prop-target", title="Authorize PGA", body="treść " * 300,
        start=BAZA - 600_000, end=BAZA + 100, voted_at=BAZA, created_at=BAZA - 700_000,
        category=kategoria_celu, native_proposal_id="0xtarget", source_domain=domena,
    )
    historia = [
        Propozycja(
            id=f"prop-{i}", title=f"Proposal {i}", body="słowo " * 200,
            start=BAZA - (i + 1) * 86_400 - 500_000,
            end=BAZA - (i + 1) * 86_400 + 100,
            voted_at=BAZA - (i + 1) * 86_400,
            created_at=BAZA - (i + 1) * 86_400 - 600_000,
            category=k, native_proposal_id=f"0x{i:04x}",
        )
        for i, k in enumerate(kategorie_historii)
    ]
    return cel, historia


def zmierz(silnik, kategorie, ekosystem=None, domena="snapshot", stan_eko="HEALTHY_COMPLETE"):
    cel, historia = zbuduj(kategorie, domena=domena)
    eko = ekosystem if ekosystem is not None else [Propozycja(id="eco-1", start=0, end=2_000_000_000)]
    pokwitowania = [
        {"source": s, "state": "HEALTHY_COMPLETE", "events": len(historia)}
        for s in ("snapshot", "governor", "taxonomy")
    ]
    pokwitowania.append({"source": "ecosystem", "state": stan_eko, "events": len(eko)})
    return silnik.compute_per_event(
        address="0xTEST",
        target_proposal=cel,
        voted_history=historia + [cel],
        now=datetime.fromtimestamp(cel.voted_at, timezone.utc),
        ecosystem_proposals=eko,
        source_receipts=pokwitowania,
    )


@pytest.fixture
def silnik():
    return FatigueEngine()


# --- I1: ta sama tożsamość znaczy ten sam wynik -----------------------------

def test_rozne_wartosci_przy_tych_samych_identyfikatorach_daja_rozne_id(silnik):
    """Kontrprzykład z 09.09: identyczne rekordy, inne kategorie, inny wynik.

    Historia ma te same `id` i `native_proposal_id` w obu przebiegach - różni je
    wyłącznie WARTOŚĆ pola `category`. Wynik jest jej funkcją przez składnik
    `novelty`, więc jeden identyfikator na dwa wyniki jest kolizją, nie zaokrągleniem.
    """
    a = zmierz(silnik, ["treasury", "treasury", "protocol"])
    b = zmierz(silnik, ["treasury", "protocol", "protocol"])

    assert a.fatigue_score != b.fatigue_score, (
        "test stracił moc: wejścia przestały różnić wynik, więc nie sprawdza już kolizji"
    )
    assert a.identity.measurement_id != b.identity.measurement_id, (
        f"kolizja: DFI {a.fatigue_score} i {b.fatigue_score} pod jednym "
        f"{a.identity.measurement_id}"
    )


# --- I1b: projekcja obejmuje pola, które czytają składniki ------------------

def test_tozsamosc_niesie_skrot_wartosci_wejsc(silnik):
    """Kryterium ZACHOWANIA, nie nazwy pola.

    Pierwsza wersja tego warunku szukała pola o nazwie zawierającej „values" -
    sprawdzała konwencję nazewniczą, nie kontrakt. Skrót ma REAGOWAĆ na zmianę
    wartości przy niezmienionych identyfikatorach.
    """
    a = zmierz(silnik, ["treasury", "treasury", "protocol"])
    b = zmierz(silnik, ["treasury", "protocol", "protocol"])

    d1 = getattr(a.identity, "canonical_input_digest", "")
    d2 = getattr(b.identity, "canonical_input_digest", "")

    assert d1 and d2, "tożsamość nie niesie skrótu wartości wejść"
    assert d1 != d2, f"skrót niezmienny mimo innych wartości: {d1[:16]}"


def test_tozsamosc_deklaruje_wersje_swojego_schematu(silnik):
    """Bez tego stare i nowe identyfikatory są nierozróżnialne inaczej niż przez commit,
    a recenzent pyta, która wersja narzędzia zebrała które dane."""
    wynik = zmierz(silnik, ["treasury", "protocol"])
    assert getattr(wynik.identity, "identity_schema_version", None)


def test_ten_sam_pomiar_dwa_razy_daje_ten_sam_identyfikator(silnik):
    """Druga strona kontraktu: identyczne wejścia nie mają prawa dać dwóch wierszy
    w rejestrze naukowym."""
    a = zmierz(silnik, ["treasury", "treasury", "protocol"])
    b = zmierz(silnik, ["treasury", "treasury", "protocol"])

    assert a.identity.measurement_id == b.identity.measurement_id
    assert a.fatigue_score == b.fatigue_score


# --- I3e: pusta ekspozycja przy celu spoza warstwy Snapshot -----------------

def test_pusta_ekspozycja_przy_celu_kontraktowym_nie_daje_pierwszorzednego_werdyktu(silnik):
    """Do 09.09 składnik `concurrency` (waga 0,25) wynosił zero dla KAŻDEGO głosu
    kontraktowego po 27.08, bo ekspozycja czytała jedną warstwę z dwóch - a werdykt
    kwalifikacyjny tego nie widział i przepuszczał taki pomiar jako pierwszorzędny.

    Cisza źródła nie ma prawa wyglądać jak mniejsze obciążenie.
    """
    wynik = zmierz(
        silnik, ["treasury", "protocol"],
        ekosystem=[], domena="governor:core", stan_eko="HEALTHY_EMPTY",
    )
    assert wynik.identity.eligibility != "PRIMARY_ELIGIBLE", (
        f"werdykt {wynik.identity.eligibility} przy concurrency "
        f"{wynik.components.concurrency} i celu z domeny governor:core"
    )
