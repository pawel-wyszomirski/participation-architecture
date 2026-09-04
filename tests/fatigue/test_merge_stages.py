"""
Unit tests for merge_stages - linking the stages of one decision into a
lifecycle WITHOUT mutating any stage.

Arbitrum runs a proposal through a Snapshot temperature check and then a binding
on-chain vote. Two Phase A participants said independently on 2026-08-05 that
the second pass is a re-read, not a second decision - so the workload windows
count a decision once. Until 2026-09-04 the function did that by collapsing
both stages into ONE object that kept the earliest timestamp but took the
longer body and the category from the later stage. The closure review of
2026-09-03 (/t/30604, point 1) named that for what it is: look-ahead leakage
through target-event mutation, and a unit of analysis that is no longer one
vote. Since then every stage is a frozen observation; the lifecycle is metadata.

The function shipped on 2026-08-05 with NO tests, and the gap it left is the
reason this file exists. Matching on the title alone merged votes 323 days apart,
because governance repeats processes under an unchanged name.

Run with: pytest tests/fatigue/test_merge_stages.py -v
"""

import pytest
import sys
import os
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import merge_stages

DZIEN = 86_400


@dataclass
class Glos:
    """Vote as the three source clients hand it over."""
    id: str
    title: str
    voted_at: int
    start: int = 0
    end: int = 0
    body: str = ""
    category: Optional[str] = None


def glos(id_, tytul, dzien, **kw):
    """A vote cast `dzien` days after an arbitrary epoch anchor."""
    t = 1_700_000_000 + dzien * DZIEN
    return Glos(id=id_, title=tytul, voted_at=t, start=t, **kw)


def cykle(wynik):
    """Distinct lifecycle ids in the result."""
    return {getattr(p, "lifecycle_id", None) for p in wynik}


# ---------------------------------------------------------------------------
# Rdzen: dwa przejscia jednej decyzji to jeden cykl - i dwie obserwacje
# ---------------------------------------------------------------------------

def test_dwa_etapy_jednej_decyzji_tworza_jeden_cykl():
    """Sonda nastrojow i glos wiazacy 12 dni pozniej = jeden cykl, dwa etapy."""
    wynik = merge_stages([
        glos("0xsnapshot", "[Constitutional] AIP: ArbOS61 Elara Upgrade", 0),
        glos("governor:core:11", "Constitutional AIP: ArbOS61 Elara Upgrade", 12),
    ])
    assert len(wynik) == 2, "no stage is absorbed"
    assert len(cykle(wynik)) == 1
    assert all(p.stages == 2 for p in wynik)
    assert [p.stage_index for p in sorted(wynik, key=lambda x: x.voted_at)] == [1, 2]


def test_roznice_zapisu_tytulu_nie_blokuja_wiazania():
    """Znaki ucieczki i nawiasy z kontraktu nie moga rozbic pary."""
    wynik = merge_stages([
        glos("0xsnap", "[Constitutional] AIP: Amended Release of Frozen ETH", 0),
        glos("governor:core:7", r"[Constitutional\] AIP: Amended Release of Frozen ETH", 9),
    ])
    assert len(cykle(wynik)) == 1


# ---------------------------------------------------------------------------
# Regresja 2026-08-06: powtarzalny tytul procesu
# ---------------------------------------------------------------------------

def test_powtorzony_cykl_pod_tym_samym_tytulem_zostaje_osobno():
    """Wybory Security Council wracaja co roku pod ta sama nazwa.

    Zmierzone na produkcji 2026-08-06: glos P02 z 2026-07-30 zostal wchloniety
    przez glos z 2025-09-10, odstep 323 dni. Zniknal NAJNOWSZY glos uczestniczki.
    """
    wynik = merge_stages([
        glos("0xstary", "[CONSTITUTIONAL] AIP: Security Council Election Process Improvements", 0),
        glos("governor:core:995", "[Constitutional] AIP: Security Council Election Process Improvements", 323),
    ])
    assert len(wynik) == 2
    assert len(cykle(wynik)) == 2, "dwa cykle tego samego procesu to dwie decyzje"
    assert all(p.stages == 1 for p in wynik)


def test_najnowszy_glos_jest_osiagalny_po_swoim_identyfikatorze():
    """Endpoint szuka celu po `id`. Wchloniety glos zwracal 404."""
    wynik = merge_stages([
        glos("0xstary", "Security Council Election Process Improvements", 0),
        glos("governor:core:995", "Security Council Election Process Improvements", 323),
    ])
    assert any(p.id == "governor:core:995" for p in wynik)


def test_drugi_etap_tez_jest_osiagalny_po_identyfikatorze():
    """Od 2026-09-04 obie strony pary sa celami: ankieta ocenia KONKRETNY glos,
    a ten moze byc glosem wiazacym, nie sonda."""
    wynik = merge_stages([
        glos("0xsnap", "ArbOS61 Elara Upgrade", 0),
        glos("governor:core:719", "ArbOS61 Elara Upgrade", 10),
    ])
    assert {p.id for p in wynik} == {"0xsnap", "governor:core:719"}


def test_najnowsze_zdarzenie_to_naprawde_najnowszy_glos():
    """Cel bez `proposal_id` = max po czasie glosu. Musi nim byc glos z konca."""
    wynik = merge_stages([
        glos("0xstary", "Security Council Election Process Improvements", 0),
        glos("governor:core:719", "ArbOS61 Elara Upgrade", 316),
        glos("governor:core:995", "Security Council Election Process Improvements", 323),
    ])
    cel = max(wynik, key=lambda p: p.voted_at)
    assert cel.id == "governor:core:995"


# ---------------------------------------------------------------------------
# Granice okna
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("odstep,zwiazane", [(44, True), (45, True), (46, False)])
def test_granica_okna(odstep, zwiazane):
    wynik = merge_stages([
        glos("0xa", "Quorum Threshold Reduction", 0),
        glos("governor:core:2", "Quorum Threshold Reduction", odstep),
    ])
    assert (len(cykle(wynik)) == 1) is zwiazane


def test_okno_jest_parametrem_nie_stala():
    para = [
        glos("0xa", "Arbitrum Audit Program", 0),
        glos("governor:core:3", "Arbitrum Audit Program", 60),
    ]
    assert len(cykle(merge_stages(list(para), okno_dni=45))) == 2
    assert len(cykle(merge_stages(list(para), okno_dni=90))) == 1


def test_lancuch_etapow_nie_zlepia_sie_ponad_okno():
    """Trzy glosy co 40 dni. Skrajne dzieli 80 dni - jeden cykl bylby bledem."""
    wynik = merge_stages([
        glos("0xa", "Domain Allocator Offerings", 0),
        glos("0xb", "Domain Allocator Offerings", 40),
        glos("0xc", "Domain Allocator Offerings", 80),
    ])
    assert len(cykle(wynik)) > 1


# ---------------------------------------------------------------------------
# Zamrozona obserwacja: etap nie dostaje NICZEGO od innego etapu
# (closure review 2026-09-03, punkt 1)
# ---------------------------------------------------------------------------

def test_cykl_niesie_najwczesniejszy_moment_a_etapy_zachowuja_wlasne():
    """Czytanie odbylo sie przy pierwszym przejsciu - to wlasnosc CYKLU.
    Kazdy etap trzyma swoj wlasny czas glosu."""
    wynik = merge_stages([
        glos("governor:core:5", "Extending DRIP Mandate", 14),
        glos("0xsnap", "Extending DRIP Mandate", 0),
    ])
    assert all(p.lifecycle_started_at == 1_700_000_000 for p in wynik)
    po_id = {p.id: p for p in wynik}
    assert po_id["0xsnap"].voted_at == 1_700_000_000
    assert po_id["governor:core:5"].voted_at == 1_700_000_000 + 14 * DZIEN


def test_tresc_pozniejszego_etapu_nie_przecieka_do_wczesniejszego():
    """Do 2026-09-04 dluzsza tresc wygrywala - obiekt o czasie t1 niosl opis
    z t2 > t1 i reading_time liczyl sie z informacji, ktorej w t1 nie bylo."""
    wynik = merge_stages([
        glos("0xsnap", "Fast Feed", 0, body="krotko"),
        glos("governor:core:9", "Fast Feed", 5, body="x" * 5000),
    ])
    po_id = {p.id: p for p in wynik}
    assert po_id["0xsnap"].body == "krotko"
    assert len(po_id["governor:core:9"].body) == 5000


def test_kategoria_pozniejszego_etapu_nie_przecieka_do_wczesniejszego():
    """Rejestr DAO kluczuje po identyfikatorze on-chain, wiec kategorie zna
    kontrakt. Etap ze Snapshota jej NIE dziedziczy - klasyfikacje nadaje mu
    osobno rejestr po tytule (ArbdataClient.przypisz_kategorie), nie sasiad."""
    wynik = merge_stages([
        glos("0xsnap", "OAT Elections", 0),
        glos("governor:core:4", "OAT Elections", 6, category="elections"),
    ])
    po_id = {p.id: p for p in wynik}
    assert po_id["0xsnap"].category is None
    assert po_id["governor:core:4"].category == "elections"


def test_kazdy_etap_zna_wszystkie_etapy_swojego_cyklu():
    wynik = merge_stages([
        glos("0xsnap", "OAT Elections", 0),
        glos("governor:core:4", "OAT Elections", 6),
    ])
    for p in wynik:
        assert sorted(p.lifecycle_stage_ids) == ["0xsnap", "governor:core:4"]
        assert p.stage_ids == [p.id], "identity carries THIS stage only"


# ---------------------------------------------------------------------------
# Niezmiennik: ten sam wklad daje ten sam wynik
# ---------------------------------------------------------------------------

def test_wynik_nie_zalezy_od_kolejnosci_zrodel():
    """Trzy zrodla odpowiadaja w dowolnej kolejnosci; pomiar ma byc ten sam."""
    a = glos("0xsnap", "Security Council Election Process Improvements", 0)
    b = glos("governor:core:995", "Security Council Election Process Improvements", 323)
    c = glos("tally:77", "Transfer 6000 ETH", 100)

    def podpis(zbior):
        return sorted((p.id, p.voted_at, p.stages, p.lifecycle_id) for p in zbior)

    assert podpis(merge_stages([a, b, c])) == podpis(merge_stages([c, b, a]))


def test_lifecycle_id_jest_deterministyczny():
    """Ten sam cykl obserwowany w dwoch pomiarach dostaje ten sam identyfikator."""
    def para():
        return [glos("0xsnap", "Fast Feed", 0), glos("governor:core:9", "Fast Feed", 5)]
    assert cykle(merge_stages(para())) == cykle(merge_stages(para()))


def test_zdarzenia_bez_tytulu_nie_sa_wiazane():
    """Pusty tytul nie jest wspolna tozsamoscia."""
    wynik = merge_stages([
        glos("0xa", "", 0),
        glos("0xb", "", 3),
    ])
    assert len(cykle(wynik)) == 2


def test_pusta_lista():
    assert merge_stages([]) == []
