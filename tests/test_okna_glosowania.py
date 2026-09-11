"""P4: dostępność źródła to nie to samo co dokładne okno głosowania.

Punkt 4 recenzji 78179. Gdy rejestr taksonomii nie zna okna propozycji kontraktowej,
klient odtwarza je arytmetycznie: czas bloku utworzenia plus `votingDelay` pomnożony
przez ŚREDNI czas bloku L1. Wynik wygląda w pomiarze identycznie jak okno wzięte
z rejestru, a oba wchodzą do `concurrency` z tą samą wagą 0,25.

Plan, sekcja 5: podstawa okna musi istnieć PER PROPOZYCJA, a `ESTIMATED` i `UNKNOWN`
nie wchodzą do współbieżności pierwszorzędnej. `GOVERNOR_EXACT` wymaga historycznego
dowodu - średni czas bloku i współczesny `votingDelay` się nie kwalifikują.

Uruchomienie: python3 -m pytest tests/test_okna_glosowania.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import (  # noqa: E402
    WINDOW_ESTIMATED, WINDOW_REGISTRY_EXACT, WINDOW_SNAPSHOT_EXACT, WINDOW_UNKNOWN,
)
from app.services.governor_client import (  # noqa: E402
    BLOCKS_PER_DAY, GovernorClient, L1_BLOCK_SECONDS,
)

CZOLO = 250_000_000
CZAS_CZOLA = 1_780_000_000
CHWILA = CZAS_CZOLA - 3600


def _pad(wartosc: int) -> str:
    return "0x" + f"{wartosc:064x}"


def _slowo(wartosc: int) -> str:
    return f"{wartosc:064x}"


def _log_utworzenia(pid: int, blok: int, *, start_l1: int, end_l1: int, opis: str) -> dict:
    """Zdarzenie ProposalCreated w kształcie, w jakim czyta je klient.

    Układ pól: proposalId, proposer, targets, values, signatures, calldatas,
    startBlock (6), endBlock (7), description (8).
    """
    opis_bajty = opis.encode()
    offset_opisu = 9 * 32
    dane = (
        _slowo(pid) + _slowo(0) + _slowo(0) + _slowo(0) + _slowo(0) + _slowo(0)
        + _slowo(start_l1) + _slowo(end_l1) + _slowo(offset_opisu)
        + _slowo(len(opis_bajty))
        + opis_bajty.hex().ljust(64, "0")
    )
    return {"data": "0x" + dane, "blockNumber": hex(blok), "topics": []}


class AtrapaWezla:
    """Węzeł RPC z zadanymi zdarzeniami i parametrami per kontrakt."""

    def __init__(self, logi_utworzen, logi_anulowan=None, voting_delay_per_adres=None):
        self.logi_utworzen = logi_utworzen
        self.logi_anulowan = logi_anulowan or {}
        self.voting_delay = voting_delay_per_adres or {}
        self.zapytania = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **k):
        metoda = (json or {}).get("method")
        parametry = (json or {}).get("params") or []
        self.zapytania.append((metoda, parametry))
        atrapa = self

        class Odpowiedz:
            status_code = 200

            def json(self_inner):
                if metoda == "eth_blockNumber":
                    return {"result": hex(CZOLO)}
                if metoda == "eth_getBlockByNumber":
                    return {"result": {"timestamp": hex(atrapa._czas_bloku(parametry[0]))}}
                if metoda == "eth_call":
                    adres = (parametry[0] or {}).get("to", "").lower()
                    return {"result": _pad(atrapa.voting_delay.get(adres, 21_600))}
                if metoda == "eth_getLogs":
                    return {"result": atrapa._logi(parametry[0])}
                return {"result": "0x0"}

        return Odpowiedz()

    def _czas_bloku(self, blok_hex):
        blok = int(blok_hex, 16) if isinstance(blok_hex, str) else int(blok_hex)
        if blok >= CZOLO:
            return CZAS_CZOLA
        return CZAS_CZOLA - (CZOLO - blok) * 86_400 // BLOCKS_PER_DAY

    def _logi(self, filtr):
        adres = (filtr.get("address") or "").lower()
        topics = filtr.get("topics") or []
        temat = topics[0] if topics else ""
        from app.services.governor_client import TOPIC_PROPOSAL_CANCELED
        if temat == TOPIC_PROPOSAL_CANCELED:
            return self.logi_anulowan.get(adres, [])
        return self.logi_utworzen.get(adres, [])


def _adresy():
    from app.services.governor_client import GOVERNORS
    return {rola: adres.lower() for rola, adres in GOVERNORS.items()}


class _RejestrPusty:
    """Rejestr taksonomii, który nie zna żadnego okna - wymusza odtworzenie."""

    async def load(self):
        return 0

    def window(self, pid):
        return None


class _RejestrZOknem:
    def __init__(self, okna):
        self.okna = okna

    async def load(self):
        return len(self.okna)

    def window(self, pid):
        return self.okna.get(str(pid))


@pytest.fixture
def bez_rejestru(monkeypatch):
    import app.services.governor_client as modul
    monkeypatch.setattr(modul, "ArbdataClient", _RejestrPusty, raising=False)
    import app.services.arbdata_client as arb
    monkeypatch.setattr(arb, "ArbdataClient", _RejestrPusty)
    return _RejestrPusty


def _podstaw_wezel(monkeypatch, wezel):
    import app.services.governor_client as modul
    monkeypatch.setattr(modul.httpx, "AsyncClient", lambda *a, **k: wezel)


@pytest.mark.asyncio
async def test_okno_odtworzone_arytmetycznie_jest_oznaczone_jako_oszacowanie(
        monkeypatch, bez_rejestru):
    """Rejestr nie zna okna, więc klient je liczy - i musi to powiedzieć.

    `opens = czas_bloku + votingDelay * 12s` opiera się na ŚREDNIM czasie bloku L1
    i na WSPÓŁCZESNEJ wartości parametru. Oszacowanie nie może wyglądać jak dowód.
    """
    adresy = _adresy()
    rola, adres = next(iter(adresy.items()))
    blok = CZOLO - BLOCKS_PER_DAY          # doba przed czołem
    logi = {adres: [_log_utworzenia(7, blok, start_l1=100, end_l1=100 + 7200,
                                    opis="# Tytul propozycji\nTresc")]}
    # `votingDelay` zero, żeby okno objęło mierzoną chwilę: domyślne 21 600 bloków to
    # przy 12 s na blok trzy doby, więc propozycja utworzona dobę przed czołem otwierałaby
    # się DWA DNI PO pomiarze i test mierzyłby pustą ekspozycję, nie podstawę okna.
    wezel = AtrapaWezla(logi, voting_delay_per_adres={adres: 0})
    _podstaw_wezel(monkeypatch, wezel)

    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte is not None, pokwitowanie.detail
    assert otwarte, "propozycja miała być otwarta w mierzonej chwili"
    for p in otwarte:
        assert p.window_basis == WINDOW_ESTIMATED, (
            f"okno policzone z czasu bloku ma być oszacowaniem, jest {p.window_basis!r}")
        assert p.window_uncertainty_reason, "oszacowanie ma nazywać, czego nie wie"


@pytest.mark.asyncio
async def test_okno_z_rejestru_jest_dowodem(monkeypatch):
    """Rejestr taksonomii zna dokładne okno - podstawa REGISTRY_EXACT."""
    import app.services.governor_client as modul
    adresy = _adresy()
    rola, adres = next(iter(adresy.items()))
    blok = CZOLO - BLOCKS_PER_DAY
    logi = {adres: [_log_utworzenia(7, blok, start_l1=100, end_l1=7300,
                                    opis="# Tytul\nTresc")]}
    rejestr = _RejestrZOknem({"7": (CHWILA - 86_400, CHWILA + 86_400)})
    monkeypatch.setattr(modul, "ArbdataClient", lambda: rejestr, raising=False)
    import app.services.arbdata_client as arb
    monkeypatch.setattr(arb, "ArbdataClient", lambda: rejestr)
    wezel = AtrapaWezla(logi)
    _podstaw_wezel(monkeypatch, wezel)

    otwarte, _ = await GovernorClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte, "propozycja z okna rejestru miała być otwarta"
    assert all(p.window_basis == WINDOW_REGISTRY_EXACT for p in otwarte)


@pytest.mark.asyncio
async def test_anulowana_propozycja_przestaje_byc_otwarta(monkeypatch, bez_rejestru):
    """Przypadek odbioru z planu: anulowanie skraca okres otwartości.

    Skanowany był wyłącznie `ProposalCreated`, więc propozycja anulowana w drugim
    dniu liczyła się do WYLICZONEGO zamknięcia - zawyżając współbieżność każdego
    głosu w tym okresie.
    """
    from app.services.governor_client import TOPIC_PROPOSAL_CANCELED
    adresy = _adresy()
    rola, adres = next(iter(adresy.items()))
    blok_utworzenia = CZOLO - 3 * BLOCKS_PER_DAY
    blok_anulowania = CZOLO - 2 * BLOCKS_PER_DAY      # dwie doby przed czołem
    logi = {adres: [_log_utworzenia(11, blok_utworzenia, start_l1=0, end_l1=100_000,
                                    opis="# Anulowana\nTresc")]}
    anulowania = {adres: [{"data": "0x" + _slowo(11), "blockNumber": hex(blok_anulowania),
                           "topics": [TOPIC_PROPOSAL_CANCELED]}]}

    # PARA KONTROLNA. Bez niej test przechodził także z wyłączoną obsługą anulowań -
    # wykrył to sabotaż. Przy domyślnym `votingDelay` (21 600 bloków, czyli trzy doby
    # przy 12 s na blok) propozycja utworzona trzy doby przed czołem otwierała się
    # DOKŁADNIE w chwili pomiaru i wypadała z ekspozycji bez związku z anulowaniem.
    # Teraz opóźnienie jest zerowe, więc jedynym powodem wypadnięcia może być anulowanie.
    bez_anulowania = AtrapaWezla(logi, voting_delay_per_adres={adres: 0})
    _podstaw_wezel(monkeypatch, bez_anulowania)
    kontrola, _ = await GovernorClient().fetch_ecosystem_exposure(CHWILA)
    assert any(p.native_proposal_id == "11" for p in (kontrola or [])), (
        "para kontrolna: bez anulowania propozycja MA być otwarta, inaczej test nie mierzy "
        "anulowania")

    wezel = AtrapaWezla(logi, logi_anulowan=anulowania,
                        voting_delay_per_adres={adres: 0})
    _podstaw_wezel(monkeypatch, wezel)

    # Mierzona chwila: godzina przed czołem, czyli PO anulowaniu.
    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte is not None, pokwitowanie.detail
    assert not any(p.native_proposal_id == "11" for p in otwarte), (
        "anulowana propozycja nadal liczy się jako otwarta")


@pytest.mark.asyncio
async def test_parametr_czytany_dla_kazdego_kontraktu_osobno(monkeypatch, bez_rejestru):
    """Dwa kontrakty z różnym `votingDelay` dają różne okna.

    Do 11.09 parametr czytano RAZ, przed pętlą po kontraktach, i stosowano do obu.
    Jedna liczba opisywała wtedy dwa różne wdrożenia.
    """
    adresy = _adresy()
    assert len(adresy) >= 2, "test wymaga dwóch kontraktów w konfiguracji"
    (rola_a, adres_a), (rola_b, adres_b) = list(adresy.items())[:2]
    blok = CZOLO - BLOCKS_PER_DAY
    logi = {
        adres_a: [_log_utworzenia(1, blok, start_l1=0, end_l1=50_000, opis="# A\nT")],
        adres_b: [_log_utworzenia(2, blok, start_l1=0, end_l1=50_000, opis="# B\nT")],
    }
    wezel = AtrapaWezla(logi, voting_delay_per_adres={adres_a: 0, adres_b: 7_200})
    _podstaw_wezel(monkeypatch, wezel)

    otwarte, _ = await GovernorClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte is not None
    per_pid = {p.native_proposal_id: p for p in otwarte}
    if "1" in per_pid and "2" in per_pid:
        assert per_pid["1"].start != per_pid["2"].start, (
            "różny votingDelay musi dać różne otwarcie okna")
    zapytania_call = [p for m, p in wezel.zapytania if m == "eth_call"]
    adresy_pytane = {(p[0] or {}).get("to", "").lower() for p in zapytania_call}
    assert {adres_a, adres_b} <= adresy_pytane, (
        f"parametr pytany tylko dla części kontraktów: {adresy_pytane}")


@pytest.mark.asyncio
async def test_ekspozycja_snapshot_niesie_podstawe_dokladna(monkeypatch):
    """Warstwa Snapshot podaje `start` i `end` wprost - to dowód, nie oszacowanie."""
    import app.services.snapshot_client as modul

    class Odp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"proposals": [
                {"id": "0xaaa", "title": "Otwarta", "start": CHWILA - 86_400,
                 "end": CHWILA + 86_400, "state": "active"}]}}

    class Klient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Odp()

    monkeypatch.setattr(modul.httpx, "AsyncClient", lambda *a, **k: Klient())
    otwarte, _ = await modul.SnapshotClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte, "propozycja miała być otwarta"
    assert all(p.window_basis == WINDOW_SNAPSHOT_EXACT for p in otwarte)


@pytest.mark.asyncio
async def test_propozycja_bez_okna_ma_podstawe_nieznana(monkeypatch, bez_rejestru):
    """Brak danych o oknie to `UNKNOWN`, nie zero i nie pominięcie w ciszy."""
    adresy = _adresy()
    rola, adres = next(iter(adresy.items()))
    blok = CZOLO - BLOCKS_PER_DAY
    # startBlock == endBlock: rozpiętość zero, czyli okno nie do odtworzenia
    logi = {adres: [_log_utworzenia(5, blok, start_l1=100, end_l1=100,
                                    opis="# Bez okna\nT")]}
    wezel = AtrapaWezla(logi, voting_delay_per_adres={adres: 0})
    _podstaw_wezel(monkeypatch, wezel)

    otwarte, pokwitowanie = await GovernorClient().fetch_ecosystem_exposure(CHWILA)

    assert otwarte is not None
    nieznane = [p for p in otwarte if p.window_basis == WINDOW_UNKNOWN]
    pominiete = not any(p.native_proposal_id == "5" for p in otwarte)
    assert nieznane or pominiete, (
        "propozycja bez odtwarzalnego okna ma być oznaczona jako UNKNOWN albo "
        "jawnie policzona w pokwitowaniu, nie zniknąć bez śladu")
    if pominiete:
        assert (pokwitowanie.unknown_window or 0) >= 1, (
            "pominięta propozycja musi zostać policzona w pokwitowaniu")


# ---------------------------------------------------------------------------
# Sekcja 5.2 planu: ESTIMATED i UNKNOWN nie wchodzą do współbieżności pierwszorzędnej
# ---------------------------------------------------------------------------

def _silnik():
    from app.services.fatigue_engine import FatigueEngine
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710})
    return eng


def _obserwacja(id_, dni_temu, podstawa, *, kategoria="grants"):
    from types import SimpleNamespace
    t = CZAS_CZOLA - dni_temu * 86_400
    return SimpleNamespace(
        id=id_, title=f"Proposal {id_}", body="tresc " * 60, state="closed",
        start=t - 86_400, end=t + 5 * 86_400, voted_at=t, cast_at=t,
        category=kategoria, source_domain="snapshot", source="snapshot",
        source_vote_id=f"v-{id_}", native_proposal_id=id_, voter="0xA",
        window_basis=podstawa, window_uncertainty_reason="",
    )


def _pokwitowania_komplet():
    from app.services.fatigue_engine import HEALTHY_COMPLETE, SourceReceipt
    zrodla = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")
    return [SourceReceipt(
        z, HEALTHY_COMPLETE, events=2, page_count=1, record_count=2, limit_hit=False,
        taxonomy_snapshot_id="tax:testowy0000000@2026-09-11" if z == "taxonomy" else "")
        for z in zrodla]


def _policz(ekspozycja):
    from datetime import datetime, timezone
    cel = _obserwacja("target", 0, WINDOW_SNAPSHOT_EXACT, kategoria="network changes")
    return _silnik().compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel],
        now=datetime.fromtimestamp(CZAS_CZOLA, timezone.utc),
        ecosystem_proposals=ekspozycja, source_receipts=_pokwitowania_komplet())


@pytest.mark.parametrize("podstawa", [WINDOW_ESTIMATED, WINDOW_UNKNOWN, ""])
def test_okno_bez_dowodu_w_ekspozycji_dyskwalifikuje_pomiar(podstawa):
    """Współbieżność liczy propozycje otwarte w mierzonej chwili.

    Okno odtworzone ze średniego czasu bloku wchodzi do tej liczby tak samo jak okno
    z rejestru, więc pomiar na takiej ekspozycji nie jest dowodem o współbieżności.
    Pusta podstawa (`""`) to warstwa, która jej nie podała - też brak dowodu, nie
    domyślnie dobry stan.
    """
    wynik = _policz([_obserwacja("eco-1", 1, podstawa)])
    assert wynik.identity.eligibility != "PRIMARY_ELIGIBLE", (
        f"ekspozycja z podstawą {podstawa!r} dała pomiar pierwszorzędny")
    assert any("window basis" in x for x in wynik.identity.eligibility_reasons), (
        f"powód ma nazywać podstawę okna: {wynik.identity.eligibility_reasons}")


@pytest.mark.parametrize("podstawa", [WINDOW_SNAPSHOT_EXACT, WINDOW_REGISTRY_EXACT])
def test_okno_z_dowodem_przechodzi(podstawa):
    """Odwrotna strona bramki - bez tego byłaby implementacją „odrzuć wszystko"."""
    wynik = _policz([_obserwacja("eco-1", 1, podstawa)])
    assert wynik.identity.eligibility == "PRIMARY_ELIGIBLE", (
        wynik.identity.eligibility_reasons)


def test_jedno_okno_bez_dowodu_psuje_cala_ekspozycje():
    """Plan, 5.2: jeżeli pominięcie rekordu może zmienić liczbę otwartych propozycji,
    cały pomiar jest niekwalifikowany - nie liczymy go jako „mniejsza współbieżność"."""
    wynik = _policz([_obserwacja("eco-1", 1, WINDOW_SNAPSHOT_EXACT),
                     _obserwacja("eco-2", 2, WINDOW_ESTIMATED)])
    assert wynik.identity.eligibility != "PRIMARY_ELIGIBLE"


# ---------------------------------------------------------------------------
# PRAWDZIWOSC ETYKIETY EXACT (uwaga recenzenta z 11.09 wieczorem)
#
# Zarzut brzmi: implementacja ma stan GOVERNOR_EXACT, a rekonstrukcja okna uzywa sredniego
# czasu bloku (BLOCKS_PER_DAY, L1_BLOCK_SECONDS) i WSPOLCZESNEJ wartosci votingDelay.
# Jesli ktokolwiek kiedys nada te etykiete takiemu oknu, powstanie dokladnie ten sam blad
# semantyczny o poziom nizej: bardzo precyzyjna nazwa "EXACT" przykryje estymacje.
#
# Dzis nikt jej nie nadaje - i te dwa testy pilnuja, zeby dodanie jej wymagalo dowodu,
# a nie tylko checi. Strażnik wpiecia, nie test przypadku.
# ---------------------------------------------------------------------------

def _zrodlo_klienta() -> str:
    from pathlib import Path
    return (Path(ROOT) / "app" / "services" / "governor_client.py").read_text(encoding="utf-8")


def test_governor_exact_nie_jest_nadawany_bez_dowodu_historycznego():
    """`GOVERNOR_EXACT` wolno nadac tylko oknu z HISTORYCZNYM dowodem start/end.

    Test pada, gdy etykieta pojawi sie w kliencie, a w kodzie nie ma jednoczesnie znacznika
    historycznego odczytu (`_voting_delay_at`, `block_time_at`, `archival`). Wtedy nalezy albo
    dostarczyc dowod, albo zostac przy `ESTIMATED` - trzeciej drogi nie ma.
    """
    zrodlo = _zrodlo_klienta()
    if "WINDOW_GOVERNOR_EXACT" not in zrodlo:
        return  # etykieta nieuzywana - stan zgodny z kontraktem
    znaczniki = ("_voting_delay_at", "block_time_at", "archival", "historyczny")
    assert any(z in zrodlo for z in znaczniki), (
        "klient nadaje GOVERNOR_EXACT, ale nie widac odczytu historycznych parametrow - "
        "etykieta EXACT przykrywa wtedy estymacje ze sredniego czasu bloku")


def test_okno_z_przybliżonego_czasu_bloku_jest_estimated(monkeypatch, bez_rejestru):
    """Behawioralna strona tej samej reguly: rekonstrukcja arytmetyczna = ESTIMATED.

    Powod `window_uncertainty_reason` musi NAZYWAC oba zrodla przyblizenia - wspolczesny
    parametr i czas bloku - zeby z pomiaru bylo widac, czego dokladnie nie wiemy.
    """
    adresy = _adresy()
    rola, adres = next(iter(adresy.items()))
    blok = CZOLO - BLOCKS_PER_DAY
    logi = {adres: [_log_utworzenia(3, blok, start_l1=0, end_l1=7200, opis="# T\nX")]}
    wezel = AtrapaWezla(logi, voting_delay_per_adres={adres: 0})
    _podstaw_wezel(monkeypatch, wezel)

    otwarte, _ = await_ekspozycji(wezel)
    assert otwarte, "propozycja miala byc otwarta"
    for p in otwarte:
        assert p.window_basis == WINDOW_ESTIMATED
        powod = (p.window_uncertainty_reason or "").lower()
        assert "votingdelay" in powod and "block" in powod, (
            f"powod nie nazywa obu zrodel przyblizenia: {powod!r}")


def await_ekspozycji(wezel):
    """Pomocnik: uruchamia asynchroniczna ekspozycje w tescie synchronicznym."""
    import asyncio
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        GovernorClient().fetch_ecosystem_exposure(CHWILA))
