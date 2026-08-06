"""
Unit tests for merge_stages - collapsing the stages of one decision.

Arbitrum runs a proposal through a Snapshot temperature check and then a binding
on-chain vote. merge_stages folds that pair into a single workload event, on the
strength of what two Phase A participants said independently on 2026-08-05:
the second pass is a re-read, not a second decision.

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


# ---------------------------------------------------------------------------
# Rdzen: dwa przejscia jednej decyzji to jedno zdarzenie
# ---------------------------------------------------------------------------

def test_dwa_etapy_jednej_decyzji_scalaja_sie():
    """Sonda nastrojow i glos wiazacy 12 dni pozniej = jedno zdarzenie."""
    wynik = merge_stages([
        glos("0xsnapshot", "[Constitutional] AIP: ArbOS61 Elara Upgrade", 0),
        glos("governor:core:11", "Constitutional AIP: ArbOS61 Elara Upgrade", 12),
    ])
    assert len(wynik) == 1
    assert wynik[0].stages == 2


def test_roznice_zapisu_tytulu_nie_blokuja_scalania():
    """Znaki ucieczki i nawiasy z kontraktu nie moga rozbic pary."""
    wynik = merge_stages([
        glos("0xsnap", "[Constitutional] AIP: Amended Release of Frozen ETH", 0),
        glos("governor:core:7", r"[Constitutional\] AIP: Amended Release of Frozen ETH", 9),
    ])
    assert len(wynik) == 1


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
    assert len(wynik) == 2, "dwa cykle tego samego procesu to dwie decyzje"
    assert {p.id for p in wynik} == {"0xstary", "governor:core:995"}
    assert all(p.stages == 1 for p in wynik)


def test_najnowszy_glos_jest_osiagalny_po_swoim_identyfikatorze():
    """Endpoint szuka celu po `id`. Wchloniety glos zwracal 404."""
    wynik = merge_stages([
        glos("0xstary", "Security Council Election Process Improvements", 0),
        glos("governor:core:995", "Security Council Election Process Improvements", 323),
    ])
    assert any(p.id == "governor:core:995" for p in wynik)


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

@pytest.mark.parametrize("odstep,scalone", [(44, True), (45, True), (46, False)])
def test_granica_okna(odstep, scalone):
    wynik = merge_stages([
        glos("0xa", "Quorum Threshold Reduction", 0),
        glos("governor:core:2", "Quorum Threshold Reduction", odstep),
    ])
    assert (len(wynik) == 1) is scalone


def test_okno_jest_parametrem_nie_stala():
    para = [
        glos("0xa", "Arbitrum Audit Program", 0),
        glos("governor:core:3", "Arbitrum Audit Program", 60),
    ]
    assert len(merge_stages(list(para), okno_dni=45)) == 2
    assert len(merge_stages(list(para), okno_dni=90)) == 1


def test_lancuch_etapow_nie_zlepia_sie_ponad_okno():
    """Trzy glosy co 40 dni. Skrajne dzieli 80 dni - jedno zdarzenie byloby bledem."""
    wynik = merge_stages([
        glos("0xa", "Domain Allocator Offerings", 0),
        glos("0xb", "Domain Allocator Offerings", 40),
        glos("0xc", "Domain Allocator Offerings", 80),
    ])
    assert len(wynik) > 1


# ---------------------------------------------------------------------------
# Wlasnosci scalonego zdarzenia
# ---------------------------------------------------------------------------

def test_scalone_zdarzenie_niesie_najwczesniejszy_moment():
    """Czytanie odbylo sie przy pierwszym przejsciu."""
    wynik = merge_stages([
        glos("governor:core:5", "Extending DRIP Mandate", 14),
        glos("0xsnap", "Extending DRIP Mandate", 0),
    ])
    assert len(wynik) == 1
    assert wynik[0].voted_at == 1_700_000_000


def test_dluzsza_tresc_wygrywa():
    """Kontrakt niesie pelny opis, Snapshot bywa skrocony."""
    wynik = merge_stages([
        glos("0xsnap", "Fast Feed", 0, body="krotko"),
        glos("governor:core:9", "Fast Feed", 5, body="x" * 5000),
    ])
    assert len(wynik[0].body) == 5000


def test_kategoria_przechodzi_z_etapu_ktory_ja_zna():
    """Rejestr DAO kluczuje po identyfikatorze on-chain, wiec kategorie niesie kontrakt."""
    wynik = merge_stages([
        glos("0xsnap", "OAT Elections", 0),
        glos("governor:core:4", "OAT Elections", 6, category="elections"),
    ])
    assert wynik[0].category == "elections"


# ---------------------------------------------------------------------------
# Niezmiennik: ten sam wklad daje ten sam wynik
# ---------------------------------------------------------------------------

def test_wynik_nie_zalezy_od_kolejnosci_zrodel():
    """Trzy zrodla odpowiadaja w dowolnej kolejnosci; pomiar ma byc ten sam."""
    a = glos("0xsnap", "Security Council Election Process Improvements", 0)
    b = glos("governor:core:995", "Security Council Election Process Improvements", 323)
    c = glos("tally:77", "Transfer 6000 ETH", 100)

    def podpis(zbior):
        return sorted((p.id, p.voted_at, getattr(p, "stages", 1)) for p in zbior)

    assert podpis(merge_stages([a, b, c])) == podpis(merge_stages([c, b, a]))


def test_zdarzenia_bez_tytulu_nie_sa_scalane():
    """Pusty tytul nie jest wspolna tozsamoscia."""
    wynik = merge_stages([
        glos("0xa", "", 0),
        glos("0xb", "", 3),
    ])
    assert len(wynik) == 2


def test_pusta_lista():
    assert merge_stages([]) == []
