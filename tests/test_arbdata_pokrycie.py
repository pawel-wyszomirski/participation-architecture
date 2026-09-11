"""D5=A: `COMPLETE` dla rejestru taksonomii ma być dowodem, nie rzutem stanu.

Stan sprzed 11.09, zmierzony: `page_count` i `limit_hit` wynosiły `None`, czyli NIE
ZMIERZONE, a `coverage_state` mimo to mówił `COMPLETE`. Komentarz przy tych polach
w `SourceReceipt` zabrania dokładnie tego: *`limit_hit=None` znaczy „nie mierzono" - to inny
stan niż `False` i nie wolno go czytać jako dowodu kompletności*.

Dowód dla TEGO źródła ma inną postać niż dla Snapshot czy governora. Rejestr przychodzi
CAŁY jednym żądaniem, bez stronicowania, więc liczba stron jest zawsze jedna i nic nie
mówi. Mówi co innego: ile rekordów przyszło, ile z nich weszło do indeksu i JAK DALEKO
sięga zbiór - bo „dostaliśmy całość" nie znaczy „całość sięga mierzonej chwili".

Pomiar z 11.09: 90 rekordów, najnowszy z 2026-08-17, czyli sprzed 25 dni.

Uruchomienie: python3 -m pytest tests/test_arbdata_pokrycie.py -q
"""
import datetime as dt
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path as _P
ROOT_PATH = _P(ROOT)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.arbdata_client import ArbdataClient, _najnowszy_rekord  # noqa: E402
from app.services.fatigue_engine import COV_COMPLETE, COV_PARTIAL_DATA  # noqa: E402


def wiersz(pid, kategoria="Grants", czas="2026-08-17T10:00:00Z"):
    return {"proposal_id": pid, "proposal_category": kategoria,
            "proposal_title": f"P{pid}", "creation_time": czas, "governor": "core"}


class _Odpowiedz:
    def __init__(self, dane):
        self._dane = dane

    def raise_for_status(self):
        return None

    def json(self):
        return self._dane


class _Klient:
    def __init__(self, dane):
        self._dane = dane

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _Odpowiedz(self._dane)


def _podstaw(monkeypatch, dane):
    import app.services.arbdata_client as ac
    monkeypatch.setattr(ac.httpx, "AsyncClient", lambda *a, **k: _Klient(dane))
    monkeypatch.setattr(ac.ArbdataClient, "_write_cache", lambda self, rows: None)


@pytest.mark.asyncio
async def test_pokwitowanie_niesie_DOWOD_a_nie_nieznane(monkeypatch):
    """`limit_hit=None` i `page_count=None` to brak pomiaru, a nie dowód kompletności."""
    _podstaw(monkeypatch, [wiersz(1), wiersz(2)])
    k = ArbdataClient()
    await k.load()

    r = k.receipt
    assert r.page_count == 1, "brak liczby żądań - nie wiadomo, czy zbiór przyszedł w całości"
    assert r.limit_hit is False, "None znaczy: nie mierzono - to nie jest dowod kompletnosci"
    assert r.record_count == 2
    assert r.coverage_state == COV_COMPLETE


@pytest.mark.asyncio
async def test_odrzucone_wiersze_to_luka_POKRYCIA_nie_dostepnosci(monkeypatch):
    """Źródło oddało komplet, instrument użył mniej - to nie jest pełne pokrycie.

    Bez tego warunku rejestr z połową wierszy bez kategorii wyglądałby tak samo, jak
    rejestr kompletny: `events` by spadło, a werdykt zostałby `COMPLETE`."""
    _podstaw(monkeypatch, [wiersz(1), {"proposal_id": None}, {"brak": "pola"}])
    k = ArbdataClient()
    await k.load()

    r = k.receipt
    assert r.record_count == 3
    assert r.events < r.record_count, "test stracił moc: nic nie zostało odrzucone"
    assert r.coverage_state == COV_PARTIAL_DATA, (
        "odrzucone rekordy nie zmieniły pokrycia - luka jest niewidoczna")
    assert "nie weszlo do indeksu" in (r.detail or "")


@pytest.mark.asyncio
async def test_zakres_rejestru_jest_w_pokwitowaniu(monkeypatch):
    """„Dostaliśmy całość" i „całość sięga mierzonej chwili" to dwa różne zdania.

    Rejestr urywa się na 2026-08-17, a pomiary idą z września - bez tego pola manifest
    nie pozwala tego rozróżnić, a `COMPLETE` brzmi jak odpowiedź na oba pytania naraz."""
    _podstaw(monkeypatch, [wiersz(1, czas="2026-03-01T00:00:00Z"),
                           wiersz(2, czas="2026-08-17T10:00:00Z")])
    k = ArbdataClient()
    await k.load()

    n = k.receipt.newest_record_at
    assert n, "pokwitowanie nie mówi, jak daleko sięga rejestr"
    assert dt.datetime.fromtimestamp(n, dt.timezone.utc).date().isoformat() == "2026-08-17"
    assert "newest_record_at" in k.receipt.to_dict(), "dowód nie dociera do manifestu"


def test_brak_pola_czasu_daje_NIE_ZMIERZONO_a_nie_zero():
    """Trzeci stan zamiast zera: rejestr bez dat nie jest rejestrem sprzed epoki."""
    assert _najnowszy_rekord([{"proposal_id": 1}]) is None
    assert _najnowszy_rekord([]) is None
    assert _najnowszy_rekord([wiersz(1, czas="2026-08-17T10:00:00Z")]) is not None


# ---------------------------------------------------------------------------
# Tally: zamrozony indeks nie jest pokryciem kompletnym
# ---------------------------------------------------------------------------

def test_tally_nie_deklaruje_kompletnego_pokrycia():
    """Zrodlo, ktorego indeks stoi od 2026-06-08, nie moze mowic COMPLETE.

    Warunek jest STATYCZNY - czyta kod, nie siec - bo chodzi o zdanie zapisane
    w manifescie, nie o zachowanie przy konkretnej odpowiedzi API. Dzis nic to nie psuje,
    bo `tally` nie stoi w `required_sources`; psuje czytelnosc manifestu dla recenzenta,
    ktory pyta, JAKI dowod pozwolil napisac COMPLETE.
    """
    kod = (ROOT_PATH / "app" / "services" / "tally_client.py").read_text(encoding="utf-8")
    assert "coverage_state=COV_PARTIAL_DATA" in kod, (
        "Tally nadal pozwala, zeby COMPLETE powstalo z rzutu stanu dostepnosci")
    assert "index frozen since" in kod, "zniknal powod, dla ktorego pokrycie jest czesciowe"
