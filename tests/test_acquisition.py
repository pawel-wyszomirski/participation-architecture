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


# ---------------------------------------------------------------------------
# Z4: kwota wnioskowana - warstwa progow finansowych byla nieosiagalna
# ---------------------------------------------------------------------------

from app.services.amount_extractor import wyciagnij, Kwota


class TestKwota:
    """Do v0.1.0 model nie mial pola z kwota, wiec `requested_amount_usd` bylo
    ZAWSZE None, a `if amount is None: return` konczylo sprawe. Cala warstwa
    progow finansowych nie odpalala sie nigdy poza testami syntetycznymi."""

    def test_dolary_z_przecinkami(self):
        assert wyciagnij("We request $1,500,000 for the program.").wartosc == 1_500_000

    def test_skrot_mnoznika(self):
        k = wyciagnij("Total budget: 2.5M ARB distributed over 6 months.")
        assert (k.wartosc, k.waluta) == (2_500_000, "ARB")

    def test_mnoznik_slowem(self):
        """`$12.8 million USD` dawalo 12,8 - wynik milion razy za maly, wygladajacy
        jak poprawna liczba. Na 200 propozycjach Arbitrum polowa kwot ponizej
        tysiaca brala sie wlasnie stad."""
        assert wyciagnij("$12.8 million USD of liquid assets").wartosc == 12_800_000
        assert wyciagnij("requesting 1.5 billion ARB").wartosc == 1_500_000_000
        assert wyciagnij("ask for 750 thousand USDC").wartosc == 750_000

    def test_brak_kwoty_to_None(self):
        assert wyciagnij("This proposal has no funding request.") is None

    def test_stan_skarbca_to_nie_wniosek(self):
        """Najwieksza liczba w tekscie zwykle opisuje tlo, nie wniosek."""
        k = wyciagnij("The DAO holds $3.2B in treasury but we ask for 100,000 ARB.")
        assert (k.wartosc, k.waluta) == (100_000, "ARB")

    def test_zdanie_sasiednie_nie_uzasadnia_liczby(self):
        """Kontekstem liczby jest JEJ zdanie. Wersja z oknem znakow brala slowo
        prosby z nastepnego zdania, bo staly blizej niz slowo tla z tego samego."""
        assert wyciagnij("Market cap is $5B. We are requesting 750,000 USDC."
                         ).wartosc == 750_000

    def test_zdanie_wylacznie_o_tle_odpada(self):
        assert wyciagnij("Treasury balance: 200M ARB. No funds requested here."
                         ) is None

    def test_arb_nie_jest_porownywalne_z_progiem_dolarowym(self):
        """Progi rulebooka sa w dolarach, a Arbitrum wnioskuje o ARB. Przeliczenie
        wymaga kursu z konkretnej chwili - modul go nie zgaduje."""
        assert wyciagnij("requesting 100,000 ARB").porownywalna_z_progiem_usd is False
        assert wyciagnij("requesting 100,000 USDC").porownywalna_z_progiem_usd is True


class TestProgFinansowyMowiOSobie:
    """Brak kwoty i kwota ponizej progu dawaly do v0.1.0 ten sam wynik: nic."""

    def _silnik(self):
        from app.services.rule_engine import RuleEngine
        return RuleEngine("rulebook.yaml")

    def _stan(self, kwota=None, waluta=None):
        from app.services.rule_engine import EvaluationState, create_test_proposal
        p = create_test_proposal(requested_amount_usd=kwota, requested_currency=waluta)
        return EvaluationState(proposal=p)

    def test_brak_kwoty_zostawia_slad(self):
        s = self._stan()
        self._silnik()._apply_treasury_tiers(s, "TRE-001")
        assert "TREASURY_AMOUNT_UNKNOWN" in s.labels

    def test_waluta_nieprzeliczalna_zostawia_inny_slad(self):
        s = self._stan(kwota=None, waluta="ARB")
        self._silnik()._apply_treasury_tiers(s, "TRE-001")
        assert "TREASURY_TIER_NOT_EVALUABLE" in s.labels
        assert any("ARB" in r for r in s.reasons)


# ---------------------------------------------------------------------------
# Z5: regula domyslna doklejala UNCATEGORIZED do propozycji sklasyfikowanej
# ---------------------------------------------------------------------------

class TestReguleDomyslna:
    """Warunek `label_count lt 2` liczyl WSZYSTKIE etykiety, razem z modyfikatorami
    typu LONG_FORM. Propozycja z jedna etykieta merytoryczna wpadala wiec w regule
    domyslna: dostawala UNCATEGORIZED obok wlasnej etykiety, a jej obsluge
    obnizano do standard_review.

    Zmierzone na v0.1.0: aktualizacja protokolu z priorytetem 80 szla do
    standard_review zamiast deep_review."""

    def _wynik(self, sciezka_rulebooka):
        import yaml
        from app.services.rule_engine import RuleEngine, create_test_proposal
        kw = yaml.safe_load(open("rulebook.yaml"))["keyword_groups"]["UPGRADE_CUES"][0]
        p = create_test_proposal(
            item_id="z5", title=f"AIP: {kw} for Arbitrum One",
            body=f"We propose a {kw}. " * 20, status="active")
        return RuleEngine(sciezka_rulebooka).evaluate_proposal(p)

    def test_sklasyfikowana_nie_dostaje_uncategorized(self):
        r = self._wynik("rulebook.yaml")
        assert "PROTOCOL_UPGRADE" in r.labels
        assert "UNCATEGORIZED" not in r.labels

    def test_obsluga_nie_jest_obnizana(self):
        r = self._wynik("rulebook.yaml")
        assert r.recommended_handling == "deep_review"

    def test_nieskasyfikowana_nadal_dostaje_uncategorized(self):
        """Regula domyslna ma dzialac tam, gdzie faktycznie brak klasyfikacji -
        poprawka nie moze jej wylaczyc."""
        from app.services.rule_engine import RuleEngine, create_test_proposal
        p = create_test_proposal(item_id="z5b", title="Weekly community call notes",
                                 body="Notes from the call. " * 10, status="active")
        r = RuleEngine("rulebook.yaml").evaluate_proposal(p)
        assert "UNCATEGORIZED" in r.labels


# ---------------------------------------------------------------------------
# Z6: czas ewaluacji jako czesc wejscia
# ---------------------------------------------------------------------------

class TestCzasEwaluacji:
    """Dwa miejsca w silniku wolaly `datetime.now()` w trakcie oceny, a znacznik
    nie byl nigdzie zapisywany. Ta sama propozycja i ten sam rulebook dawaly
    pozniej inny werdykt BEZ zmiany wejscia - przy naglowku deklarujacym
    determinizm."""

    def _silnik(self):
        from app.services.rule_engine import RuleEngine
        return RuleEngine("rulebook.yaml")

    def _propozycja(self, koniec):
        from app.services.rule_engine import create_test_proposal
        return create_test_proposal(
            item_id="z6", title="Community update on operations",
            body="Operational note. " * 40, status="active", end_at=koniec)

    def test_ten_sam_czas_daje_ten_sam_wynik(self):
        import time
        t = int(time.time())
        e = self._silnik()
        a = e.evaluate_proposal(self._propozycja(t + 36000), evaluated_at=t)
        b = e.evaluate_proposal(self._propozycja(t + 36000), evaluated_at=t)
        assert a.priority_score == b.priority_score
        assert a.labels == b.labels

    def test_czas_realnie_zmienia_wynik_wiec_musi_byc_wejsciem(self):
        """Gdyby czas nie zmienial wyniku, zamrozenie byloby kosmetyka.
        Zmienia: ta sama propozycja oceniona przed i po zamknieciu glosowania."""
        import time
        t = int(time.time())
        e = self._silnik()
        przed = e.evaluate_proposal(self._propozycja(t + 36000), evaluated_at=t)
        po = e.evaluate_proposal(self._propozycja(t + 36000), evaluated_at=t + 72000)
        assert przed.priority_score != po.priority_score

    def test_znacznik_wraca_w_wyniku(self):
        """Bez zapisanego znacznika nie da sie odtworzyc oceny z przeszlosci."""
        import time
        t = int(time.time())
        r = self._silnik().evaluate_proposal(self._propozycja(t + 3600), evaluated_at=t)
        assert r.explain["evaluated_at"] == t


# ---------------------------------------------------------------------------
# Z7: slad decyzji, nie samo dopasowanie warunku
# ---------------------------------------------------------------------------

class TestSladDecyzji:
    """`reasons` mowilo wylacznie, ze warunek reguly sie dopasowal. Nie dalo sie
    odczytac, czy dzialanie zastosowano, czy nadpisala je regula o wyzszym
    priorytecie - a to jest roznica miedzy 'regula zadziala' a 'regula probowala'."""

    def _wynik(self):
        import time, yaml
        from app.services.rule_engine import RuleEngine, create_test_proposal
        kw = yaml.safe_load(open("rulebook.yaml"))["keyword_groups"]["UPGRADE_CUES"][0]
        p = create_test_proposal(item_id="z7", title=f"AIP: {kw}",
                                 body=f"{kw} " * 30, status="active")
        return RuleEngine("rulebook.yaml").evaluate_proposal(
            p, evaluated_at=int(time.time()))

    def test_slad_wymienia_zadane_dzialania(self):
        wpisy = self._wynik().explain["audit"]
        assert wpisy, "slad audytu pusty"
        assert all("requested" in w for w in wpisy)

    def test_slad_odroznia_zastosowane_od_pominietych(self):
        wpisy = self._wynik().explain["audit"]
        assert all("applied" in w and "skipped" in w for w in wpisy)

    def test_kazdy_wpis_wskazuje_regule(self):
        wpisy = self._wynik().explain["audit"]
        assert all(w.get("rule") for w in wpisy)


# ---------------------------------------------------------------------------
# Z8: brak rulebooka nie moze konczyc sie pustym zestawem regul
# ---------------------------------------------------------------------------

class TestRulebookZamykaSie:
    """Do v0.1.0 brakujacy plik zwracal {"rules": []}, silnik wstawal, a usluga
    zglaszala gotowosc. Kazda propozycja przechodzila przez ZERO regul i dostawala
    wynik domyslny - nie do odroznienia od propozycji, ktora zadnej reguly nie
    spelnila. Triaz bez regul odpowiada tak samo jak triaz dzialajacy."""

    def test_brak_pliku_rzuca(self, tmp_path):
        from app.services.rule_engine import RuleEngine
        with pytest.raises(FileNotFoundError):
            RuleEngine(str(tmp_path / "nie-ma.yaml"))

    def test_rulebook_bez_regul_rzuca(self, tmp_path):
        from app.services.rule_engine import RuleEngine
        pusty = tmp_path / "pusty.yaml"
        pusty.write_text("version: '1.0'\nrules: []\n")
        with pytest.raises(ValueError):
            RuleEngine(str(pusty))

    def test_rulebook_nie_bedacy_mapa_rzuca(self, tmp_path):
        from app.services.rule_engine import RuleEngine
        zly = tmp_path / "zly.yaml"
        zly.write_text("- to\n- jest\n- lista\n")
        with pytest.raises(ValueError):
            RuleEngine(str(zly))


# ---------------------------------------------------------------------------
# Z13, Z14: sprawnosc mierzona, nie deklarowana
# ---------------------------------------------------------------------------

class TestHealthcheck:
    """`status` bylo stala "ok". Odpowiedz brzmiala HTTP 200 i "ok" przy
    `database: disconnected` i obu silnikach nieuruchomionych - monitoring
    widzial usluge zdrowa, gdy nie mogla nic zrobic."""

    def test_status_nie_jest_stala_w_kodzie(self):
        import pathlib
        zrodlo = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        assert 'status="ok",' not in zrodlo, "status wpisany na sztywno wrocil"

    def test_pusty_korpus_to_brak_gotowosci(self):
        """Z14: kontener wstawal na pustej bazie i odpowiadal poprawnie.
        Triaz bez korpusu nie ma czego triazowac."""
        import pathlib
        zrodlo = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        assert "proposal corpus empty" in zrodlo

    def test_odpowiedz_niesie_powod_braku_gotowosci(self):
        import pathlib
        zrodlo = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        assert "not_ready" in zrodlo and "503" in zrodlo


class TestWdrozenie:
    def test_sterownik_bazy_zadeklarowany(self):
        """Z12: compose podaje URL z +asyncpg, session.py przepisuje go na
        +psycopg2, a sterownik nie byl w requirements. Czysta instalacja nie
        mogla polaczyc sie z PostgreSQL."""
        import pathlib
        assert "psycopg2" in pathlib.Path("requirements.txt").read_text()

    def test_start_kontenera_zasila_korpus(self):
        """Z14: CMD uruchamial sam serwer."""
        import pathlib
        assert "entrypoint.sh" in pathlib.Path("Dockerfile").read_text()
        wejscie = pathlib.Path("entrypoint.sh").read_text()
        assert "snapshot_client" in wejscie
        assert "INGEST_ON_START" in wejscie


# ---------------------------------------------------------------------------
# Z9, Z10, Z11: walidacja i raport
# ---------------------------------------------------------------------------

class TestRaportNieZamieniaZeraWDowod:
    """Najciezszy zarzut z czternastki, bo dotyczy dokumentu opublikowanego jako
    produkt grantu.

    generate_pdf_report.py mial:
        if analysis['sec_001_analysis']['count'] == 0:
            conclusions.append("SEC-001-STRICT: No false positives.
                                Rule correctly identifies only active security incidents.")

    `count` to liczba ODPALEN reguly, nie falszywych trafien. Zero odpalen
    zamienialo sie we wniosek o poprawnosci dzialania. Korpus zawieral wylacznie
    propozycje zamkniete, a regula wymaga `not_flag: STATE_CLOSED` - zero bylo
    wynikiem konstrukcji, nie pomiarem."""

    def _zrodlo(self, plik):
        import pathlib
        return pathlib.Path(plik).read_text(encoding="utf-8")

    def test_wniosek_o_poprawnosci_zniknal(self):
        z = self._zrodlo("scripts/generate_pdf_report.py")
        # wystepuje juz tylko w komentarzu opisujacym usterke
        linie = [l for l in z.splitlines()
                 if "Rule correctly identifies" in l and not l.strip().startswith("#")]
        assert not linie, f"twierdzenie o poprawnosci wrocilo: {linie}"

    def test_raport_podaje_kwalifikowalnosc(self):
        """Liczba odpalen bez liczby propozycji, ktore MOGLY odpalic, nie znaczy nic."""
        z = self._zrodlo("scripts/generate_pdf_report.py")
        assert "sec_001_eligible" in z
        assert "NOT EVALUABLE" in z

    def test_komorka_falszywych_trafien_niesie_falszywe_trafienia(self):
        """W tabeli stala LICZBA ODPALEN pod etykieta "False Positives", ze statusem
        wpisanym na sztywno. Przy pieciu odpaleniach pokazalaby "5, None"."""
        z = self._zrodlo("scripts/generate_pdf_report.py")
        assert "['SEC-001 False Positives', str(analysis['sec_001_analysis']['count']), '✓ None']" not in z

    def test_heurystyka_nie_udaje_oznaczonej_prawdy(self):
        """Z9: falszywe trafienia wykrywa lista slow w tytule, na tym samym
        korpusie, na ktorym strojono reguly. Raport ma to mowic."""
        z = self._zrodlo("scripts/generate_pdf_report.py")
        assert "not independently labelled ground truth" in z


class TestWalidacjaLiczyPokrycie:
    def test_wynik_niesie_stan_propozycji(self):
        import pathlib
        z = pathlib.Path("scripts/validate_ex_ante.py").read_text(encoding="utf-8")
        assert "'state': row['state']" in z

    def test_analiza_liczy_kwalifikujace_sie(self):
        import pathlib
        z = pathlib.Path("scripts/validate_ex_ante.py").read_text(encoding="utf-8")
        assert "sec_001_eligible" in z and "by_state" in z
