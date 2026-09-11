"""D5=A: `COMPLETE` dla governora ma być DOWODEM pokrycia, nie wnioskiem z braku wyjątku.

Zarzut recenzenta zewnętrznego z 11.09, potwierdzony pomiarem: `limit_hit` i `page_count`
występowały wyłącznie w `snapshot_client`. Dla governora `coverage_state` powstawał z rzutu
stanu dostępności, więc odpowiadał na pytanie „czy klient zadziałał", a nie „czy objęliśmy
zakres, o który pytaliśmy".

Skan chodzi po ZAKRESIE BLOKÓW podzielonym na okna. Dowodem pokrycia jest tu komplet okien,
które odpowiedziały - nie liczba stron jak w Snapshot, bo semantyka źródła jest inna.

Znalezione przy naprawie: `res.get("result") or []` sprowadzało dwa stany do pustej listy -
odpowiedź z pustym wynikiem ORAZ odpowiedź BEZ pola `result`. `_call` rzuca, gdy żaden węzeł
nie odpowie, ale węzeł potrafi zwrócić 200 z ciałem bez `error` i bez `result`; wtedy okno
znikało po cichu, a skan wyglądał na kompletny.

Uruchomienie: python3 -m pytest tests/test_governor_pokrycie.py -q
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import COV_COMPLETE, PARTIAL  # noqa: E402
from app.services.governor_client import GovernorClient  # noqa: E402

GLOS = {
    "data": "0x" + "00" * 31 + "07" + "00" * 32 + "00" * 32,
    "blockNumber": "0x1",
}


class _Klient:
    """Atrapa httpx.AsyncClient - nic nie wysyła."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _ustaw(monkeypatch, odpowiedzi):
    """`odpowiedzi` to lista wyników kolejnych wywołań `eth_getLogs`."""
    import app.services.governor_client as gc
    monkeypatch.setattr(gc.httpx, "AsyncClient", lambda *a, **k: _Klient())
    kolejka = list(odpowiedzi)

    async def falszywe_call(self, client, method, params):
        if method == "eth_blockNumber":
            return {"result": hex(10_000_000)}
        if method == "eth_getLogs":
            return kolejka.pop(0) if kolejka else {"result": []}
        return {"result": "0x" + "00" * 32}

    monkeypatch.setattr(gc.GovernorClient, "_call", falszywe_call)


@pytest.mark.asyncio
async def test_okno_bez_pola_result_nie_udaje_pustego_wyniku(monkeypatch):
    """Odpowiedź BEZ `result` to brak wyniku, nie zero zdarzeń.

    Do 11.09 oba stany dawały pustą listę, więc kawałek historii znikał bez śladu,
    a pokwitowanie mówiło `HEALTHY_COMPLETE`."""
    klient = GovernorClient()
    # Pierwsze okno odpowiada pusto, drugie NIE ODPOWIADA (200 bez `result`).
    _ustaw(monkeypatch, [{"result": []}, {"jsonrpc": "2.0", "id": 1}])

    logi = await klient._logs(_Klient(), ["0xtopic"], 0, 10_000_000)

    assert logi == []
    skan = klient._ostatni_skan
    assert skan["okien"] > 0
    assert skan["okien_z_odpowiedzia"] < skan["okien"], (
        "okno bez pola `result` policzono jako odpowiedź - luka pokrycia jest niewidoczna")


@pytest.mark.asyncio
async def test_komplet_okien_daje_pelne_pokrycie(monkeypatch):
    """Warunek odwrotny: bez niego naprawa byłaby implementacją „zawsze niekompletne"."""
    klient = GovernorClient()
    _ustaw(monkeypatch, [])          # każde okno odpowiada pustym wynikiem

    await klient._logs(_Klient(), ["0xtopic"], 0, 10_000_000)

    skan = klient._ostatni_skan
    assert skan["okien"] == skan["okien_z_odpowiedzia"] > 0


@pytest.mark.asyncio
async def test_pokwitowanie_governora_niesie_dowod_pokrycia(monkeypatch):
    """Dowód ma dojść do POKWITOWANIA - inaczej kwalifikacja go nie zobaczy.

    To ta sama lekcja, co z serializacją manifestu: wartość policzona i nieprzekazana
    nie istnieje dla warstwy, która ją sprawdza."""
    klient = GovernorClient()
    _ustaw(monkeypatch, [])

    _, pokwitowanie = await klient.fetch_voted_observations("0x" + "aa" * 20, days=6)

    assert pokwitowanie.source == "governor"
    assert pokwitowanie.page_count > 0, "pokwitowanie nie niesie liczby okien skanu"
    assert pokwitowanie.limit_hit is False
    assert hasattr(pokwitowanie, "coverage_state")
