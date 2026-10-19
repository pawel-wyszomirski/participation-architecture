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
import json
import os
import sys

import httpx
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path as _P
ROOT_PATH = _P(ROOT)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.arbdata_client import ArbdataClient, _najnowszy_rekord  # noqa: E402
from app.services.fatigue_engine import COV_COMPLETE, COV_PARTIAL_DATA  # noqa: E402


FROZEN = ["proposal_title", "proposal_category", "proposal_theme", "proposal_type",
          "creation_time", "voting_end_time", "outcome"]
KOLUMNY = ["proposal_number"] + FROZEN


def wiersz(pid, kategoria="Grants", czas="2026-08-17T10:00:00Z"):
    return {"proposal_number": pid, "proposal_id": pid, "proposal_category": kategoria,
            "proposal_title": f"P{pid}", "creation_time": czas, "governor": "core",
            "proposal_theme": "", "proposal_type": "constitutional",
            "voting_end_time": "2026-09-01 10:00:00", "outcome": "Passed"}


def wykres(rekordy, kolumny=KOLUMNY):
    """Odpowiedz trasy danych wykresu (format od 19.10): wiersze-tablice plus `columns`."""
    return {"columns": [{"name": c, "type": "String"} for c in kolumny],
            "rows": [[r.get(c) for c in kolumny] for r in rekordy],
            "row_count": len(rekordy)}


def mapa(tmp_path, rekordy):
    """Zamrozona mapa `proposal_number -> proposal_id` w ksztalcie app/services/arbdata_proposal_keys.json."""
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"frozen_fields": FROZEN, "keys": {
        str(r["proposal_number"]): {"proposal_id": r.get("proposal_id"),
                                    "governor": r.get("governor"), "proposer_name": None,
                                    "frozen": {f: r.get(f) for f in FROZEN}}
        for r in rekordy}}))
    return p


class _Odpowiedz:
    def __init__(self, dane, status=200):
        self._dane = dane
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://api.entropydata.co/x")
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=req,
                response=httpx.Response(self.status_code, request=req))

    def json(self):
        return self._dane


class _Serwer:
    """Atrapa platformy: konfiguracja strony wydaje klucz, trasa danych oddaje wykres,
    a pierwsze `odmowy` zadan o dane odbija 403 jak wygasly klucz."""

    def __init__(self, dane, odmowy=0):
        self._dane = dane
        self.odmowy = odmowy
        self.wydane_klucze = 0
        self.klucze_w_zadaniach = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        import app.services.arbdata_client as ac
        if url == ac.SITE_ENDPOINT:
            self.wydane_klucze += 1
            return _Odpowiedz({"data_key": f"klucz-{self.wydane_klucze}"})
        self.klucze_w_zadaniach.append((k.get("params") or {}).get("key"))
        if self.odmowy:
            self.odmowy -= 1
            return _Odpowiedz({"error": {"code": "data_key_invalid"}}, status=403)
        return _Odpowiedz(self._dane)


def _podstaw(monkeypatch, dane, odmowy=0):
    import app.services.arbdata_client as ac
    serwer = _Serwer(dane, odmowy)
    monkeypatch.setattr(ac.httpx, "AsyncClient", lambda *a, **k: serwer)
    monkeypatch.setattr(ac.ArbdataClient, "_write_cache", lambda self, rows: None)
    return serwer


def _klient(tmp_path, rekordy_mapy, kopia=None):
    return ArbdataClient(keys_path=mapa(tmp_path, rekordy_mapy),
                         cache_path=kopia or (tmp_path / "brak-kopii.json"))


@pytest.mark.asyncio
async def test_pokwitowanie_niesie_DOWOD_a_nie_nieznane(monkeypatch, tmp_path):
    """`limit_hit=None` i `page_count=None` to brak pomiaru, a nie dowód kompletności."""
    rek = [wiersz(1), wiersz(2)]
    _podstaw(monkeypatch, wykres(rek))
    k = _klient(tmp_path, rek)
    await k.load()

    r = k.receipt
    assert r.page_count == 1, "brak liczby żądań - nie wiadomo, czy zbiór przyszedł w całości"
    assert r.limit_hit is False, "None znaczy: nie mierzono - to nie jest dowod kompletnosci"
    assert r.record_count == 2
    assert r.coverage_state == COV_COMPLETE


@pytest.mark.asyncio
async def test_odrzucone_wiersze_to_luka_POKRYCIA_nie_dostepnosci(monkeypatch, tmp_path):
    """Źródło oddało komplet, instrument użył mniej - to nie jest pełne pokrycie.

    Bez tego warunku rejestr z połową wierszy bez kategorii wyglądałby tak samo, jak
    rejestr kompletny: `events` by spadło, a werdykt zostałby `COMPLETE`."""
    rek = [wiersz(1), wiersz(2), wiersz(3)]
    rek[1]["proposal_id"] = None          # wpis mapy bez identyfikatora on-chain
    rek[2]["proposal_id"] = "nie-liczba"
    _podstaw(monkeypatch, wykres(rek))
    k = _klient(tmp_path, rek)
    await k.load()

    r = k.receipt
    assert r.record_count == 3
    assert r.events < r.record_count, "test stracił moc: nic nie zostało odrzucone"
    assert r.coverage_state == COV_PARTIAL_DATA, (
        "odrzucone rekordy nie zmieniły pokrycia - luka jest niewidoczna")
    assert "nie weszlo do indeksu" in (r.detail or "")


@pytest.mark.asyncio
async def test_zakres_rejestru_jest_w_pokwitowaniu(monkeypatch, tmp_path):
    """„Dostaliśmy całość" i „całość sięga mierzonej chwili" to dwa różne zdania.

    Rejestr urywa się na 2026-08-17, a pomiary idą z września - bez tego pola manifest
    nie pozwala tego rozróżnić, a `COMPLETE` brzmi jak odpowiedź na oba pytania naraz."""
    rek = [wiersz(1, czas="2026-03-01T00:00:00Z"), wiersz(2, czas="2026-08-17T10:00:00Z")]
    _podstaw(monkeypatch, wykres(rek))
    k = _klient(tmp_path, rek)
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


# ---------------------------------------------------------------------------
# Nowy format zrodla (19.10): wykres Entropy Data + zamrozona mapa kluczy on-chain
# ---------------------------------------------------------------------------

FIKSTURA = ROOT_PATH / "tests" / "fixtures" / "arbdata-chart-2026-10-19.json"
MAPA_KLUCZY = ROOT_PATH / "app" / "services" / "arbdata_proposal_keys.json"
PID_90 = 104933844856336554027758452704713321330340501652892001249184191934279866979282


def _fikstura():
    return json.loads(FIKSTURA.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_prawdziwa_odpowiedz_wykresu_daje_te_same_okna_i_kategorie(monkeypatch, tmp_path):
    """Trzy rekordy z odpowiedzi z 19.10 przez prawdziwa mape kluczy: okno, kategoria
    i governor maja byc dokladnie te, ktore dawal stary rejestr dla tego samego id."""
    from app.services.arbdata_client import _epoch
    _podstaw(monkeypatch, _fikstura())
    k = ArbdataClient(keys_path=MAPA_KLUCZY, cache_path=tmp_path / "brak.json")
    assert await k.load() == 3
    assert k.receipt.state == "HEALTHY_COMPLETE"
    assert k.receipt.coverage_state == COV_COMPLETE
    assert k.subject(PID_90) == ("Network Changes", "")
    assert k.governor(PID_90) == "core"
    assert k.window(PID_90) == (_epoch("2026-08-17 20:05:05"), _epoch("2026-09-04 07:57:47"))
    assert k.kategoria_po_tytule(
        "Authorize Priority Gas Auctions and Establish the Fast Feed") == "Network Changes"


@pytest.mark.asyncio
async def test_kolumny_mapowane_po_nazwie_nie_po_pozycji(monkeypatch, tmp_path):
    """Serwer moze zmienic kolejnosc kolumn; wynik nie ma prawa sie od tego zmienic."""
    dane = _fikstura()
    nazwy = [c["name"] for c in dane["columns"]]
    kolejnosc = list(reversed(range(len(nazwy))))
    dane["columns"] = [dane["columns"][i] for i in kolejnosc]
    dane["rows"] = [[w[i] for i in kolejnosc] for w in dane["rows"]]
    _podstaw(monkeypatch, dane)
    k = ArbdataClient(keys_path=MAPA_KLUCZY, cache_path=tmp_path / "brak.json")
    assert await k.load() == 3
    assert k.subject(PID_90) == ("Network Changes", "")


@pytest.mark.asyncio
async def test_identyfikator_taksonomii_ten_sam_co_z_kopii(monkeypatch, tmp_path):
    """Skrot zbioru kategorii liczy sie z par (proposal_id, kategoria) - po odtworzeniu
    klucza z mapy musi wyjsc ten sam, co z kopii starego rejestru dla tych rekordow."""
    _podstaw(monkeypatch, _fikstura())
    k = ArbdataClient(keys_path=MAPA_KLUCZY, cache_path=tmp_path / "brak.json")
    await k.load()
    klucze = json.loads(MAPA_KLUCZY.read_text(encoding="utf-8"))["keys"]
    stare = [{"proposal_id": klucze[n]["proposal_id"],
              "proposal_category": klucze[n]["frozen"]["proposal_category"]}
             for n in ("90", "61", "12")]
    dzien = k.receipt.taxonomy_snapshot_id.split("@")[1]
    assert k.receipt.taxonomy_snapshot_id == ArbdataClient.snapshot_id(stare, dzien)


@pytest.mark.asyncio
async def test_rekord_spoza_mapy_to_luka_POKRYCIA(monkeypatch, tmp_path):
    """Nowa propozycja bez klucza on-chain nie ma okna ani kategorii dla zdarzen z kontraktu.
    Pokwitowanie mowi ILE takich rekordow i KIEDY powstal najnowszy - nie milczy."""
    stare = [wiersz(1), wiersz(2)]
    nowy = wiersz(3, czas="2026-10-01 12:00:00")
    _podstaw(monkeypatch, wykres(stare + [nowy]))
    k = _klient(tmp_path, stare)
    assert await k.load() == 2
    r = k.receipt
    assert r.coverage_state == COV_PARTIAL_DATA
    assert r.record_count == 3 and r.events == 2
    assert r.unknown_window == 1
    assert r.unknown_window_newest_at == int(
        dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc).timestamp())
    assert "mapie kluczy" in r.detail
    assert k.window(3) is None


@pytest.mark.asyncio
async def test_zmieniona_tresc_starego_rekordu_to_ERROR_nie_ciche_przyjecie(monkeypatch, tmp_path):
    """Kategoria albo okno przepisane po stronie zrodla zmieniloby historyczny wynik pod
    tym samym identyfikatorem. Caly odczyt zostaje odrzucony, indeks pusty."""
    rek = [wiersz(1), wiersz(2)]
    zmienione = [dict(rek[0]), dict(rek[1], proposal_category="Incentives")]
    _podstaw(monkeypatch, wykres(zmienione))
    k = _klient(tmp_path, rek)
    assert await k.load() == 0
    assert k.receipt.state == "ERROR"
    assert "content drift" in k.receipt.detail and "#2" in k.receipt.detail
    assert len(k) == 0


@pytest.mark.asyncio
async def test_rozjazd_tresci_przy_kopii_idzie_jako_PARTIAL_z_powodem(monkeypatch, tmp_path):
    """Z kopia w reku odczyt nie znika, ale pokwitowanie nie udaje odpowiedzi na zywo."""
    rek = [wiersz(1)]
    kopia = tmp_path / "kopia.json"
    kopia.write_text(json.dumps({"fetched_at": "2026-09-16T15:08:09+00:00", "rows": rek}))
    _podstaw(monkeypatch, wykres([dict(rek[0], voting_end_time="2026-09-03 10:00:00")]))
    k = _klient(tmp_path, rek, kopia=kopia)
    await k.load()
    assert k.receipt.state == "PARTIAL"
    assert "content drift" in k.receipt.detail and "2026-09-16" in k.receipt.detail


@pytest.mark.asyncio
async def test_403_klucza_jedno_ponowienie_ze_swiezym_kluczem(monkeypatch, tmp_path):
    rek = [wiersz(1)]
    serwer = _podstaw(monkeypatch, wykres(rek), odmowy=1)
    k = _klient(tmp_path, rek)
    assert await k.load() == 1
    assert k.receipt.state == "HEALTHY_COMPLETE"
    assert serwer.klucze_w_zadaniach == ["klucz-1", "klucz-2"], "ponowienie bez nowego klucza"


@pytest.mark.asyncio
async def test_drugie_403_to_ERROR(monkeypatch, tmp_path):
    rek = [wiersz(1)]
    serwer = _podstaw(monkeypatch, wykres(rek), odmowy=2)
    k = _klient(tmp_path, rek)
    assert await k.load() == 0
    assert k.receipt.state == "ERROR"
    assert k.receipt.detail == "HTTP 403"
    assert serwer.wydane_klucze == 2, "wiecej niz jedno ponowienie"


@pytest.mark.asyncio
async def test_strona_krotsza_niz_row_count_to_ERROR(monkeypatch, tmp_path):
    rek = [wiersz(1), wiersz(2)]
    dane = wykres(rek)
    dane["row_count"] = 5
    _podstaw(monkeypatch, dane)
    k = _klient(tmp_path, rek)
    assert await k.load() == 0
    assert k.receipt.state == "ERROR"
    assert "truncated" in k.receipt.detail


def test_mapa_kluczy_pochodzi_z_kopii_z_16_09_i_jest_kompletna():
    """Mapa jest zamrozonym artefaktem, nie wynikiem liczonym w locie: niesie pochodzenie,
    a jej 90 wpisow ma unikalne identyfikatory on-chain."""
    m = json.loads(MAPA_KLUCZY.read_text(encoding="utf-8"))
    assert m["origin"]["fetched_at"].startswith("2026-09-16")
    assert len(m["origin"]["sha256"]) == 64
    assert len(m["keys"]) == m["origin"]["rows"] == 90
    ids = [w["proposal_id"] for w in m["keys"].values()]
    assert len(set(ids)) == 90 and all(str(i).isdigit() for i in ids)
