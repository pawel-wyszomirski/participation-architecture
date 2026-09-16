# <!-- catalog-read --> sprawdzone: tests/ nie ma pliku o kliencie Tally
"""Klient Tally stronicuje - obciety zbior nie moze wygladac jak pelny (16.09).

Tally tnie strone do 20 pozycji NIEZALEZNIE od parametru `limit`, a warunek urwania
w kliencie brzmial `len(nodes) >= 100`. Nie mogl trafic ani razu: serwer nigdy nie oddawal
stu rekordow. Skutek byl podwojny - `fetch_arbitrum_proposals` widzial 20 propozycji z 87
deklarowanych przez `pageInfo.count`, a pokwitowanie mowilo HEALTHY_COMPLETE o jednej
stronie wyniku.

Zmierzone po naprawie na zywym koncie: glosow delegata 20 -> 77.

To ta sama klasa, ktora projekt lapal juz przy Snapshocie (`skip` powyzej 5000) i przy
rejestrze Tally w pomiarze cyklu zycia DAO: WYNIK OBCIETY WYGLADA IDENTYCZNIE JAK PELNY.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.tally_client import TallyClient  # noqa: E402


class _Klient(TallyClient):
    """Klient z podstawionym transportem - bez sieci i bez klucza."""

    def __init__(self, strony):
        self.url, self.key, self.headers = "", "x", {}
        self._strony = strony
        self.wywolania = []

    async def _post(self, query, variables):
        self.wywolania.append(variables)
        return self._strony[min(len(self.wywolania) - 1, len(self._strony) - 1)]


def _strona(klucz, ids, kursor, count):
    return {"data": {klucz: {
        "nodes": [{"id": str(i), "metadata": {"title": f"P{i}", "description": "x"},
                   "start": {"timestamp": "2026-05-14T21:49:59Z"},
                   "end": {"timestamp": "2026-05-28T22:55:59Z"}} for i in ids],
        "pageInfo": {"lastCursor": kursor, "count": count}}}}


@pytest.mark.asyncio
async def test_zbiera_wszystkie_strony_nie_pierwsza():
    """Trzy strony po 20 to 60 rekordow, nie 20."""
    k = _Klient([_strona("proposals", range(0, 20), "k1", 60),
                 _strona("proposals", range(20, 40), "k2", 60),
                 _strona("proposals", range(40, 60), None, 60)])
    rekordy, urwane, deklarowana = await k._wszystkie_strony(
        "q", {"filters": {}}, "proposals")
    assert len(rekordy) == 60, "klient ma zejsc po wszystkie strony"
    assert urwane is False
    assert deklarowana == 60


@pytest.mark.asyncio
async def test_kursor_idzie_do_zapytania():
    """Druga strona pyta z `afterCursor` - bez tego petla czytalaby tę samą stronę."""
    k = _Klient([_strona("proposals", range(0, 20), "k1", 40),
                 _strona("proposals", range(20, 40), None, 40)])
    await k._wszystkie_strony("q", {"filters": {}}, "proposals")
    assert k.wywolania[0]["in"]["page"].get("afterCursor") is None
    assert k.wywolania[1]["in"]["page"]["afterCursor"] == "k1"


@pytest.mark.asyncio
async def test_sufit_stron_jest_urwaniem_a_naturalny_koniec_nie():
    """Rozroznienie decyduje o pokwitowaniu: TRUNCATED wobec HEALTHY_COMPLETE."""
    bez_konca = _Klient([_strona("proposals", range(0, 20), "wciaz-dalej", 9999)])
    _, urwane, _ = await bez_konca._wszystkie_strony(
        "q", {"filters": {}}, "proposals", sufit_stron=3)
    assert urwane is True, "zatrzymanie sufitem stron to urwanie"

    domkniety = _Klient([_strona("proposals", range(0, 5), None, 5)])
    _, urwane2, _ = await domkniety._wszystkie_strony("q", {"filters": {}}, "proposals")
    assert urwane2 is False, "naturalny koniec nie jest urwaniem"


@pytest.mark.asyncio
async def test_powtorzony_rekord_nie_dubluje_zbioru():
    """Ten sam identyfikator na dwoch stronach to jeden rekord, nie dwa."""
    k = _Klient([_strona("proposals", [1, 2, 3], "k1", 4),
                 _strona("proposals", [3, 4], None, 4)])
    rekordy, _, _ = await k._wszystkie_strony("q", {"filters": {}}, "proposals")
    assert len(rekordy) == 4, f"oczekiwano czterech unikatow, jest {len(rekordy)}"


@pytest.mark.asyncio
async def test_niepelne_GLOSY_tez_sa_urwaniem():
    """Sprawdzenie krzyzowe z `pageInfo.count` obejmuje OBA zapytania, nie tylko propozycje.

    Pierwsza wersja naprawy z 16.09 porownywala deklarowana liczbe wylacznie dla PROPOZYCJI,
    a dla GLOSOW odrzucala ja podkreslnikiem - czyli ten sam mechanizm awarii, ktory commit
    naprawial, zostawal otwarty o jedna sciezke dalej. Znalazl to przeglad kodu, nie test:
    `fetch_voted_observations` testow nie mialo.

    Rodzina bledu: poprawka jednej sciezki przy nietknietej drugiej.
    """
    strony = {}

    class _Dwa(TallyClient):
        def __init__(self):
            self.url, self.key, self.headers = "", "x", {}
            self.wywolania = 0

        async def _post(self, query, variables):
            self.wywolania += 1
            # pierwsze zapytanie: propozycje komplet (2 z 2); drugie: glosy urwane (1 z 9)
            if self.wywolania == 1:
                return {"data": {"proposals": {
                    "nodes": [{"id": "p1", "metadata": {"title": "A", "description": "x"},
                               "start": {"timestamp": "2026-05-14T21:49:59Z"}},
                              {"id": "p2", "metadata": {"title": "B", "description": "x"},
                               "start": {"timestamp": "2026-05-14T21:49:59Z"}}],
                    "pageInfo": {"lastCursor": None, "count": 2}}}}
            return {"data": {"votes": {
                "nodes": [{"id": "v1", "block": {"timestamp": "2026-05-20T10:00:00Z"},
                           "proposal": {"id": "p1"}}],
                "pageInfo": {"lastCursor": None, "count": 9}}}}

    _, receipt = await _Dwa().fetch_voted_observations("0xA")
    assert receipt.state == "TRUNCATED", (
        f"jeden glos przy dziewieciu deklarowanych to zbior urwany, nie komplet: {receipt.state}")
    assert "votes" in (receipt.detail or ""), (
        f"powod ma nazwac, KTORE zapytanie jest niepelne: {receipt.detail!r}")
