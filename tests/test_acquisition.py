"""Testy pobierania po naprawie v0.2.0 - zarzuty Z1, Z2, Z3.

Recenzja zrodlowa v0.1.0 wskazala trzy usterki w tej warstwie i kazda potwierdzila
sie w kodzie. Te testy pilnuja, zeby nie wrocily.

Bez sieci - klient HTTP podstawiany.
"""
import pytest
from datetime import datetime, timezone

from app.services.snapshot_client import (
    SnapshotClient, AcquisitionError, AcquisitionReceipt, _odcisk_tresci,
)


class _Odp:
    def __init__(self, status=200, dane=None, tekst=""):
        self.status_code = status
        self._dane = dane
        self.text = tekst

    def json(self):
        if self._dane is None:
            raise ValueError("nie JSON")
        return self._dane


class _Klient:
    """Podstawiony httpx.AsyncClient - oddaje kolejne odpowiedzi z listy."""
    def __init__(self, odpowiedzi):
        self.odpowiedzi = list(odpowiedzi)
        self.zapytania = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self.zapytania.append(json["variables"])
        if not self.odpowiedzi:
            raise AssertionError("wiecej zapytan niz przygotowanych odpowiedzi")
        o = self.odpowiedzi.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


def _propozycje(ile, od=0):
    return [{"id": f"p{i}", "title": f"T{i}", "body": "x", "start": 1, "end": 2,
             "state": "closed", "author": "0x", "votes": 1, "scores_total": 1.0}
            for i in range(od, od + ile)]


def _podstaw(monkeypatch, klient):
    import app.services.snapshot_client as m
    monkeypatch.setattr(m.httpx, "AsyncClient", lambda *a, **k: klient)


# ---------------------------------------------------------------------------
# Z1: stan propozycji nie moze byc wpisany na sztywno
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_domyslnie_pobiera_wszystkie_stany(monkeypatch):
    """v0.1.0 miala `state: "closed"` w zapytaniu, a produkt jest opisany jako
    triaz propozycji BIEZACYCH - nie mogl zobaczyc ani jednej otwartej."""
    k = _Klient([_Odp(dane={"data": {"proposals": _propozycje(3)}})])
    _podstaw(monkeypatch, k)
    await SnapshotClient().fetch_proposals(page_size=10)
    assert k.zapytania[0]["state"] is None


@pytest.mark.asyncio
async def test_stan_da_sie_zawezic(monkeypatch):
    k = _Klient([_Odp(dane={"data": {"proposals": _propozycje(2)}})])
    _podstaw(monkeypatch, k)
    await SnapshotClient().fetch_proposals(state="active", page_size=10)
    assert k.zapytania[0]["state"] == "active"


# ---------------------------------------------------------------------------
# Z2: stronicowanie i pokwitowanie kompletnosci
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chodzi_po_stronach_do_wyczerpania(monkeypatch):
    """v0.1.0 pytala raz, `skip: 0`. Wszystko poza pierwsza strona nie istnialo."""
    k = _Klient([
        _Odp(dane={"data": {"proposals": _propozycje(10, 0)}}),
        _Odp(dane={"data": {"proposals": _propozycje(10, 10)}}),
        _Odp(dane={"data": {"proposals": _propozycje(4, 20)}}),   # krotka = koniec
    ])
    _podstaw(monkeypatch, k)
    p, r = await SnapshotClient().fetch_proposals(page_size=10)
    assert len(p) == 24
    assert r.pages == 3
    assert r.complete is True
    assert [z["skip"] for z in k.zapytania] == [0, 10, 20]


@pytest.mark.asyncio
async def test_limit_wolajacego_znaczy_niekompletne(monkeypatch):
    """Liczba rekordow sama nie mowi, czy strumien sie skonczyl, czy przycial go
    limit. Kazde twierdzenie o pokryciu musi stac na pokwitowaniu."""
    k = _Klient([
        _Odp(dane={"data": {"proposals": _propozycje(10, 0)}}),
        _Odp(dane={"data": {"proposals": _propozycje(5, 10)}}),
    ])
    _podstaw(monkeypatch, k)
    p, r = await SnapshotClient().fetch_proposals(page_size=10, max_items=15)
    assert len(p) == 15
    assert r.complete is False


# ---------------------------------------------------------------------------
# Z2: awaria NIE moze wygladac jak pusty wynik
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_awaria_polaczenia_rzuca(monkeypatch):
    _podstaw(monkeypatch, _Klient([OSError("sieci brak")]))
    with pytest.raises(AcquisitionError):
        await SnapshotClient().fetch_proposals(page_size=10)


@pytest.mark.asyncio
async def test_blad_http_rzuca(monkeypatch):
    _podstaw(monkeypatch, _Klient([_Odp(status=503, tekst="unavailable")]))
    with pytest.raises(AcquisitionError):
        await SnapshotClient().fetch_proposals(page_size=10)


@pytest.mark.asyncio
async def test_blad_graphql_rzuca(monkeypatch):
    """Snapshot potrafi oddac HTTP 200 z polem `errors` i pustym `data`.
    v0.1.0 zwracala wtedy pusta liste, nie do odroznienia od braku propozycji."""
    _podstaw(monkeypatch, _Klient([
        _Odp(dane={"errors": [{"message": "query too complex"}], "data": None})]))
    with pytest.raises(AcquisitionError):
        await SnapshotClient().fetch_proposals(page_size=10)


@pytest.mark.asyncio
async def test_brak_pola_proposals_rzuca(monkeypatch):
    """Zmiana schematu po stronie zrodla ma byc bledem, nie cicha pustka."""
    _podstaw(monkeypatch, _Klient([_Odp(dane={"data": {}})]))
    with pytest.raises(AcquisitionError):
        await SnapshotClient().fetch_proposals(page_size=10)


@pytest.mark.asyncio
async def test_prawdziwie_pusty_wynik_to_nie_awaria(monkeypatch):
    """Rozroznienie dziala w obie strony: brak propozycji jest poprawna
    odpowiedzia i ma dac pokwitowanie, nie wyjatek."""
    _podstaw(monkeypatch, _Klient([_Odp(dane={"data": {"proposals": []}})]))
    p, r = await SnapshotClient().fetch_proposals(page_size=10)
    assert p == []
    assert r.fetched == 0
    assert r.complete is True


# ---------------------------------------------------------------------------
# Z3: odcisk tresci
# ---------------------------------------------------------------------------

def test_odcisk_zmienia_sie_ze_trescia():
    a = {"title": "T", "body": "tresc", "start": 1, "end": 2}
    b = {"title": "T", "body": "tresc poprawiona", "start": 1, "end": 2}
    assert _odcisk_tresci(a) != _odcisk_tresci(b)


def test_odcisk_nie_zalezy_od_glosow():
    """Zmiana liczby glosow to nie zmiana tekstu - klasyfikacja jej nie widzi."""
    a = {"title": "T", "body": "x", "start": 1, "end": 2, "votes": 5}
    b = {"title": "T", "body": "x", "start": 1, "end": 2, "votes": 900}
    assert _odcisk_tresci(a) == _odcisk_tresci(b)
