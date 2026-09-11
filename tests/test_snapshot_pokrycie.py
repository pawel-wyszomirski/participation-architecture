"""P2 sekcja 3.3: pokrycie zbioru musi być MIERZONE przy pozyskaniu, nie zakładane.

`fetch_voted_observations` wysyłał JEDNO zapytanie `first: 200` i przy pełnej stronie
zwracał pokwitowanie `TRUNCATED`. Wykrycie limitu jest, dowodu pokrycia nie ma - a od
11.09 to `coverage_state` rozstrzyga o wejściu do analizy konfirmacyjnej, więc delegat
z ponad dwustoma głosami wypadałby z rundy N=50 z powodu limitu strony, nie z powodu
własności pomiaru.

Reguła planu: zbiór większy od limitu ma wrócić W CAŁOŚCI albo jako `TRUNCATED` -
nigdy jako `COMPLETE`. Dowodem kompletności są liczniki (`page_count`, `record_count`,
`limit_hit`), nie brak podejrzeń.

Uruchomienie: python3 -m pytest tests/test_snapshot_pokrycie.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import (  # noqa: E402
    AVAIL_HEALTHY, COV_COMPLETE, COV_TRUNCATED, HEALTHY_COMPLETE, TRUNCATED,
)
from app.services.snapshot_client import SnapshotClient  # noqa: E402

ADDR = "0x00000000000000000000000000000000000000aa"
BAZA_CZASU = 1_780_000_000


class _AtrapaOdpowiedzi:
    def __init__(self, dane):
        self._dane = dane

    def raise_for_status(self):
        return None

    def json(self):
        return self._dane


class _AtrapaKlienta:
    """Snapshot z zadaną liczbą głosów, odpowiadający stronami jak prawdziwy.

    Sortowanie `created desc` i filtr `created_lt` z zapytania są respektowane -
    bez tego test mierzyłby atrapę, nie stronicowanie.
    """

    def __init__(self, ile_glosow: int, rejestr: list):
        self._glosy = [
            {
                "id": f"vote-{i}",
                "created": BAZA_CZASU - i * 3600,
                "proposal": {
                    "id": f"prop-{i}",
                    "title": f"Proposal {i}",
                    "body": "word " * 100,
                    "start": BAZA_CZASU - i * 3600 - 86_400,
                    "end": BAZA_CZASU - i * 3600 + 86_400,
                    "state": "closed",
                },
            }
            for i in range(ile_glosow)
        ]
        self._rejestr = rejestr

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        zmienne = (json or {}).get("variables") or {}
        first = int(zmienne.get("first") or 0)
        przed = zmienne.get("created_lt")
        self._rejestr.append({"first": first, "created_lt": przed})
        pula = self._glosy
        if przed is not None:
            pula = [g for g in pula if g["created"] < int(przed)]
        return _AtrapaOdpowiedzi({"data": {"votes": pula[:first]}})


def _podstaw(monkeypatch, ile_glosow, rejestr):
    import app.services.snapshot_client as modul

    def fabryka(*a, **k):
        return _AtrapaKlienta(ile_glosow, rejestr)

    monkeypatch.setattr(modul.httpx, "AsyncClient", fabryka)


@pytest.mark.asyncio
async def test_zbior_mniejszy_od_limitu_jest_kompletny_z_dowodem(monkeypatch):
    rejestr = []
    _podstaw(monkeypatch, 40, rejestr)
    obserwacje, pokwitowanie = await SnapshotClient().fetch_voted_observations(ADDR, limit=200)

    assert len(obserwacje) == 40
    assert pokwitowanie.state == HEALTHY_COMPLETE
    assert pokwitowanie.availability_state == AVAIL_HEALTHY
    assert pokwitowanie.coverage_state == COV_COMPLETE
    assert pokwitowanie.limit_hit is False, "limit_hit=None znaczy 'nie mierzono' - to nie dowód"
    assert pokwitowanie.page_count == 1
    assert pokwitowanie.record_count == 40
    assert len(rejestr) == 1


@pytest.mark.asyncio
async def test_zbior_wiekszy_od_strony_wraca_w_calosci(monkeypatch):
    """Trzysta głosów przy stronie stu: trzy strony plus domknięcie, zero dziur.

    Do 11.09 wracało sto rekordów z pokwitowaniem TRUNCATED, czyli delegat
    z długą historią nie mógł dać pomiaru pierwszorzędnego.
    """
    rejestr = []
    _podstaw(monkeypatch, 300, rejestr)
    obserwacje, pokwitowanie = await SnapshotClient().fetch_voted_observations(ADDR, limit=100)

    assert len(obserwacje) == 300, f"zbiór obcięty do {len(obserwacje)}"
    assert pokwitowanie.coverage_state == COV_COMPLETE
    assert pokwitowanie.limit_hit is False
    assert pokwitowanie.page_count >= 3
    assert pokwitowanie.record_count == 300
    # Ciągłość: żaden identyfikator nie powtarza się i żaden nie wypadł.
    ident = [o.native_proposal_id for o in obserwacje]
    assert len(set(ident)) == 300
    # Stronicowanie idzie po czasie, nie po `skip` - Snapshot odrzuca `skip` powyżej 5000,
    # a wynik obcięty sufitem wygląda identycznie jak pełny.
    assert any(z["created_lt"] is not None for z in rejestr)


@pytest.mark.asyncio
async def test_sufit_stron_konczy_sie_truncated_nie_cisza(monkeypatch):
    """Gdy historia przekracza sufit stron, pokwitowanie MUSI to powiedzieć.

    Alternatywa - ciche zwrócenie tego, co się zebrało - jest tą samą klasą błędu,
    którą naprawiamy: niepełny zbiór wyglądałby jak pełny.
    """
    rejestr = []
    _podstaw(monkeypatch, 5000, rejestr)
    obserwacje, pokwitowanie = await SnapshotClient().fetch_voted_observations(
        ADDR, limit=100, max_stron=3)

    assert len(obserwacje) == 300
    assert pokwitowanie.state == TRUNCATED
    assert pokwitowanie.coverage_state == COV_TRUNCATED
    assert pokwitowanie.limit_hit is True
    assert pokwitowanie.page_count == 3
    assert "3" in (pokwitowanie.detail or ""), "detail ma nazwać sufit, o który się odbiliśmy"
