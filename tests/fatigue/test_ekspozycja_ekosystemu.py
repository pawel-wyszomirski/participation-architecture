"""
Ecosystem exposure: the concurrency component (weight 0.25) and three ways it can
be wrong without looking wrong.

Written 2026-09-09 as the passing criteria for the second round of I3 repairs,
BEFORE the code changed. The whole DFI increase reported that day (22.0→27.5,
43.9→50.6, 39.8→46.1) comes from this component, so an exposure defect goes
straight into the dissertation numbers.

1. A PARTIAL failure is not a layer failure. Two Governor contracts are scanned;
   when one answers 403 and the other returns proposals, the function returned the
   proposals WITH an ERROR receipt, `_scal_ekspozycje` saw a non-None value and
   merged, and the verdict came out PRIMARY_ELIGIBLE on an incomplete ecosystem.
   `ecosystem_governor` was not in required_sources either, so eligibility never
   looked at that receipt.

2. The scan window was anchored to the chain HEAD, not to the measured moment.
   `as_of` is the instrument's primary mode, and a measurement older than days_back
   found NOTHING while the receipt said HEALTHY_COMPLETE - because the receipt
   described the SCAN, not the exposure.

3. The merge key was untested in both directions. Normalising the title can split
   one decision into two (overcount) or collapse two into one (undercount); the test
   double always returned [], so `_scal_ekspozycje` never once ran with two non-empty
   lists.

Run with: pytest tests/fatigue/test_ekspozycja_ekosystemu.py -v
"""

import os
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services import governor_client as gc
from app.services.fatigue_engine import FatigueEngine, scal_ekspozycje
from app.services.governor_client import BLOCKS_PER_DAY, GovernorClient
from app.services.fatigue_engine import ERROR, HEALTHY_COMPLETE, HEALTHY_EMPTY


# ── kodowanie zdarzenia ProposalCreated ────────────────────────────────────

def _pad(v: int) -> str:
    return f"{v:064x}"


def _encode_string(text: str) -> str:
    raw = text.encode("utf-8").hex()
    return _pad(len(text.encode("utf-8"))) + raw + "0" * ((64 - len(raw) % 64) % 64)


def log_propozycji(pid: int, blok: int, span_blokow: int, opis: str) -> dict:
    """Zdarzenie w układzie, który czyta `fetch_ecosystem_exposure`:
    słowo 0 = identyfikator, 6 i 7 = bloki startu i końca, 8 = offset opisu."""
    slowa = [_pad(pid)] + [_pad(0)] * 5 + [_pad(0), _pad(span_blokow), _pad(9 * 32)]
    return {"data": "0x" + "".join(slowa) + _encode_string(opis),
            "blockNumber": hex(blok)}


@dataclass
class Propozycja:
    id: str
    title: str = ""
    start: int = 0
    end: int = 0
    source_domain: str = "snapshot"
    native_proposal_id: str = ""


HEAD = 300_000_000
TERAZ = 1_780_000_000


@pytest.fixture
def tor(monkeypatch):
    """Atrapa łańcucha. `zakresy` zapisuje granice KAŻDEGO skanu - to nimi mierzymy,
    czy okno kotwiczy się w mierzonej chwili, czy w HEAD."""
    stan = {"zakresy": [], "logi": {}, "anulowania": {}, "bledy": set()}

    async def _block_number(self, client):
        return HEAD

    async def _voting_delay(self, client):
        return 0

    async def _logs(self, client, topics, first, last):
        rola = next((r for r, a in gc.GOVERNORS.items() if a == self.address), "?")
        stan["zakresy"].append((rola, first, last))
        if rola in stan["bledy"]:
            raise RuntimeError("HTTP 403")
        # Atrapa ROZROZNIA zdarzenia (od 11.09, P4). Przedtem oddawala te same logi na
        # kazde zapytanie, wiec skan anulowan czytal zdarzenia utworzenia jako anulowania
        # i propozycja otwarta wypadala z ekspozycji. Atrapa, ktora nie rozroznia tego,
        # co rozroznia zrodlo, mierzy sama siebie.
        if topics and topics[0] == gc.TOPIC_PROPOSAL_CANCELED:
            return [l for b, l in stan.get("anulowania", {}).get(rola, [])
                    if first <= b <= last]
        return [l for b, l in stan["logi"].get(rola, []) if first <= b <= last]

    async def _block_time(self, client, block_hex):
        # Jeden blok = ćwierć sekundy, zgodnie z BLOCKS_PER_DAY klienta.
        return TERAZ - (HEAD - int(block_hex, 16)) * 86_400 // BLOCKS_PER_DAY

    class PustyRejestr:
        async def load(self):
            return None

        def window(self, pid):
            return None

    monkeypatch.setattr(GovernorClient, "_block_number", _block_number)
    monkeypatch.setattr(GovernorClient, "_voting_delay", _voting_delay)
    monkeypatch.setattr(GovernorClient, "_logs", _logs)
    monkeypatch.setattr(GovernorClient, "_block_time", _block_time)
    monkeypatch.setattr("app.services.arbdata_client.ArbdataClient", PustyRejestr)
    return stan


# ── 1. awaria częściowa nie jest awarią warstwy ────────────────────────────

@pytest.mark.asyncio
async def test_jeden_kontrakt_odmawia_drugi_odpowiada_to_nie_jest_pomiar(tor):
    """403 na jednym kontrakcie przy propozycjach z drugiego dawał listę ze stanem ERROR.
    Wołający widział wartość nie-None i scalał - ekspozycja niepełna szła jako pomiar."""
    role = list(gc.GOVERNORS)
    tor["bledy"].add(role[0])
    tor["logi"][role[1]] = [(HEAD - 1000, log_propozycji(1, HEAD - 1000, 100_000, "AIP: Fund X"))]

    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(TERAZ)

    assert pokwitowanie.state == ERROR
    assert otwarte is None, (
        "częściowa odpowiedź podana jako ekspozycja - stan zdegradowany przechodzi jako pomiar"
    )


@pytest.mark.asyncio
async def test_oba_kontrakty_odpowiadaja_daje_pomiar(tor):
    """Kontrola przeciwna: bez awarii wynik ma być listą, nie None."""
    role = list(gc.GOVERNORS)
    tor["logi"][role[0]] = [(HEAD - 1000, log_propozycji(1, HEAD - 1000, 100_000, "AIP: Fund X"))]

    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(TERAZ)

    assert otwarte is not None and len(otwarte) == 1
    assert pokwitowanie.state in (HEALTHY_COMPLETE, HEALTHY_EMPTY)


def test_warstwa_kontraktowa_jest_zrodlem_wymaganym():
    """Bez tego wpisu kwalifikacja nigdy nie ogląda pokwitowania `ecosystem_governor`,
    więc awaria tej warstwy nie ma jak zdyskwalifikować pomiaru."""
    silnik = FatigueEngine()
    wymagane = (silnik.config.get("eligibility") or {}).get("required_sources") or []
    assert "ecosystem_governor" in wymagane


# ── 2. okno skanu kotwiczy się w mierzonej chwili ──────────────────────────

@pytest.mark.asyncio
async def test_okno_skanu_idzie_za_mierzona_chwila_nie_za_head(tor):
    """Tryb `as_of` jest podstawowym trybem instrumentu. Przy pomiarze sprzed roku
    zakres liczony od HEAD nie obejmuje ocenianej chwili i nie znajduje NICZEGO."""
    rok_temu = TERAZ - 365 * 86_400
    await GovernorClient().fetch_ecosystem_exposure(rok_temu, days_back=120)

    blok_chwili = HEAD - (TERAZ - rok_temu) * BLOCKS_PER_DAY // 86_400
    for rola, first, last in tor["zakresy"]:
        assert first <= blok_chwili <= last, (
            f"{rola}: zakres {first}-{last} nie obejmuje bloku mierzonej chwili {blok_chwili}"
        )


@pytest.mark.asyncio
async def test_pokwitowanie_orzeka_o_ekspozycji_nie_o_udanym_skanie(tor):
    """Skan może się udać i nic nie znaleźć z dwóch różnych powodów: nic nie było
    otwarte (pomiar) albo pytaliśmy poza zakresem (brak pomiaru). HEALTHY_COMPLETE
    dla tego drugiego przypadku to cisza podana jako zero."""
    daleka_przeszlosc = TERAZ - 3650 * 86_400
    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(
        daleka_przeszlosc, days_back=120)

    assert not (pokwitowanie.state == HEALTHY_COMPLETE and not otwarte), (
        "pokwitowanie opisuje udany skan, nie ekspozycję przy mierzonej chwili"
    )


# ── 3. klucz scalania w obie strony ────────────────────────────────────────

def test_ta_sama_decyzja_z_dwoch_warstw_liczy_sie_raz():
    """Etap na Snapshocie i etap na kontrakcie to jedna decyzja - delegat czyta ją raz.
    Suma list policzyłaby dwa obciążenia tam, gdzie było jedno."""
    snap = [Propozycja(id="s1", title="Constitutional AIP: ArbOS 61 Elara Upgrade",
                       start=100, end=200)]
    gov = [Propozycja(id="g1", title="[Constitutional] AIP: ArbOS61 Elara Upgrade",
                      start=150, end=260, source_domain="governor:core")]

    scalone = scal_ekspozycje(snap, gov)

    assert len(scalone) == 1, [p.title for p in scalone]
    assert scalone[0].source_domain.startswith("governor"), (
        "przy tej samej decyzji zostaje etap wiążący - jego okno opisuje realny czas obciążenia"
    )


def test_dwie_rozne_propozycje_tej_samej_warstwy_nie_sklejaja_sie():
    """Normalizacja zdejmuje `aip`, `proposal`, `constitutional` i całą interpunkcję,
    więc dwie różne decyzje mogą zejść się do jednego klucza. W obrębie JEDNEJ warstwy
    to zawsze dwa obciążenia - governance nie wystawia jednej propozycji dwa razy."""
    gov = [
        Propozycja(id="g1", title="AIP: Funding Proposal", start=100, end=200,
                   source_domain="governor:core", native_proposal_id="111"),
        Propozycja(id="g2", title="Proposal: Funding (AIP)", start=120, end=220,
                   source_domain="governor:core", native_proposal_id="222"),
    ]

    scalone = scal_ekspozycje([], gov)

    assert len(scalone) == 2, (
        f"dwie decyzje kontraktowe zlane w jedną - współczynnik zaniżony: "
        f"{[p.id for p in scalone]}"
    )


def test_awaria_ktorejkolwiek_warstwy_zostaje_brakiem_pomiaru():
    assert scal_ekspozycje(None, []) is None
    assert scal_ekspozycje([], None) is None
    assert scal_ekspozycje([], []) == []


def test_propozycje_bez_tytulu_nie_zlewaja_sie_w_jedna():
    """Pusty klucz nie może scalić wszystkiego, co go nie ma."""
    snap = [Propozycja(id="s1", title="", start=1, end=2),
            Propozycja(id="s2", title="", start=3, end=4)]

    assert len(scal_ekspozycje(snap, [])) == 2
