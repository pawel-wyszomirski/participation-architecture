"""Tests for GovernorClient - ABI decoding and RPC failure handling, no network.

The point of this client is that a source which cannot answer must never look
like a source that answered "nothing". Tally failing that distinction is what
hid six real votes from the pilot participants.
"""
import pytest

from app.services.governor_client import (
    GovernorClient,
    _string_at,
    _title_from_description,
    _word,
)


def _pad(value: int) -> str:
    return f"{value:064x}"


def _encode_string(text: str) -> str:
    raw = text.encode("utf-8").hex()
    padded = raw + "0" * ((64 - len(raw) % 64) % 64)
    return _pad(len(text.encode("utf-8"))) + padded


class TestSlowoAbi:
    def test_pierwsze_slowo_to_identyfikator(self):
        data = "0x" + _pad(12345) + _pad(1)
        assert _word(data, 0) == 12345

    def test_kolejne_slowa_po_indeksie(self):
        data = "0x" + _pad(7) + _pad(99) + _pad(2)
        assert _word(data, 1) == 99
        assert _word(data, 2) == 2

    def test_brakujace_slowo_daje_zero_zamiast_wyjatku(self):
        # Ucięty payload nie może wywrócić skanu całego okna.
        assert _word("0x" + _pad(1), 5) == 0

    def test_dziala_bez_prefiksu_0x(self):
        assert _word(_pad(42), 0) == 42


class TestDekodowanieOpisu:
    def test_odczytuje_string_spod_offsetu(self):
        opis = "Constitutional AIP: ArbOS61 Elara Upgrade"
        # slowa 0..1 to dane statyczne, slowo 2 trzyma offset (w bajtach)
        data = "0x" + _pad(1) + _pad(2) + _pad(3 * 32) + _encode_string(opis)
        assert _string_at(data, 2) == opis

    def test_uszkodzony_offset_daje_pusty_string(self):
        assert _string_at("0x" + _pad(999999), 0) == ""

    def test_znaki_wielobajtowe_nie_gina(self):
        opis = "Propozycja — zmiana progów"
        data = "0x" + _pad(0) + _pad(2 * 32) + _encode_string(opis)
        assert _string_at(data, 1) == opis


class TestTytulZOpisu:
    def test_bierze_pierwsza_niepusta_linie(self):
        assert _title_from_description("\n\nArbOS61 Elara\n\nDetails follow") == "ArbOS61 Elara"

    def test_zdejmuje_krzyzyki_naglowka_markdown(self):
        assert _title_from_description("# Continued Funding") == "Continued Funding"

    def test_pusty_opis_ma_wartosc_zastepcza(self):
        assert _title_from_description("   \n  \n") == "(untitled proposal)"

    def test_bardzo_dlugi_tytul_jest_przycinany(self):
        assert len(_title_from_description("x" * 500)) == 200


class TestOdpornoscRpc:
    @pytest.mark.asyncio
    async def test_wszystkie_wezly_odmawiaja_to_blad_nie_pustka(self):
        """Odmowa węzła musi być wyjątkiem, nie cichym brakiem głosów."""
        class OdmawiajacyKlient:
            async def post(self, *a, **k):
                class R:
                    status_code = 403
                    def json(self): return {}
                return R()

        klient = GovernorClient(endpoints=["https://a", "https://b"])
        with pytest.raises(RuntimeError) as e:
            await klient._call(OdmawiajacyKlient(), "eth_blockNumber", [])
        assert "403" in str(e.value)

    @pytest.mark.asyncio
    async def test_przechodzi_na_kolejny_wezel_po_bledzie(self):
        wywolania = []

        class Klient:
            async def post(self, url, **k):
                wywolania.append(url)
                class R:
                    status_code = 200 if url == "https://drugi" else 500
                    def json(self_inner): return {"result": "0x10"}
                return R()

        klient = GovernorClient(endpoints=["https://pierwszy", "https://drugi"])
        odp = await klient._call(Klient(), "eth_blockNumber", [])
        assert odp["result"] == "0x10"
        assert wywolania == ["https://pierwszy", "https://drugi"]
        # zapamiętany działający węzeł idzie pierwszy przy kolejnym wywołaniu
        assert klient._endpoint == "https://drugi"

    @pytest.mark.asyncio
    async def test_blad_w_ciele_odpowiedzi_tez_przelacza_wezel(self):
        """JSON-RPC zwraca 200 z polem error - to nadal awaria źródła."""
        class Klient:
            async def post(self, url, **k):
                class R:
                    status_code = 200
                    def json(self_inner):
                        if url == "https://zly":
                            return {"error": {"code": -32005, "message": "limit exceeded"}}
                        return {"result": "0x20"}
                return R()

        klient = GovernorClient(endpoints=["https://zly", "https://dobry"])
        odp = await klient._call(Klient(), "eth_blockNumber", [])
        assert odp["result"] == "0x20"


class TestOknaGlosowania:
    """Okres głosowania odtwarzany ze zdarzenia ProposalCreated.

    Do 2026-08-05 klient wpisywał w `start` czas bloku GŁOSU i nie ustawiał
    `end` wcale. Skutek: warunek współbieżności `start <= as_of <= end` nie
    zachodził nigdy, więc ŻADEN głos on-chain nie wchodził do składnika o wadze
    25% - a od czerwca to jedyna droga głosowania na Arbitrum. Cicha zera,
    nie do odróżnienia od realnego braku nakładania się propozycji.

    Druga pułapka: `startBlock` i `endBlock` to numery bloków ETHEREUM, nie
    Arbitrum (Arbitrum zwraca w `block.number` wysokość L1). Przeliczenie ich
    węzłem Arbitrum trafiłoby w blok bez związku ze sprawą.
    """

    @pytest.mark.asyncio
    async def test_votingdelay_czytany_z_kontraktu(self):
        class Klient:
            async def post(self, url, json=None, **k):
                class R:
                    status_code = 200
                    def json(self_inner):
                        return {"result": _pad(21600)}
                return R()

        klient = GovernorClient(endpoints=["https://x"])
        assert await klient._voting_delay(Klient()) == 21600

    @pytest.mark.asyncio
    async def test_awaria_odczytu_daje_wartosc_domyslna_nie_brak_okna(self):
        """Nieodczytane opóźnienie nie może skasować okna - brak okna znaczy
        zero współbieżności u wszystkich, czyli gorzej niż okno przybliżone."""
        from app.services.governor_client import DEFAULT_VOTING_DELAY_BLOCKS

        class Klient:
            async def post(self, *a, **k):
                class R:
                    status_code = 500
                    def json(self_inner): return {}
                return R()

        klient = GovernorClient(endpoints=["https://x"])
        assert await klient._voting_delay(Klient()) == DEFAULT_VOTING_DELAY_BLOCKS

    def test_dlugosc_okna_liczona_ze_zdarzenia_nie_ze_stalej(self):
        """`endBlock - startBlock` bierzemy per propozycja, bo parametry
        zarządzania bywają zmieniane, a stara propozycja ma odtworzyć się
        według reguł, które obowiązywały przy jej tworzeniu."""
        from app.services.governor_client import L1_BLOCK_SECONDS

        start_block, end_block = 25_547_165, 25_647_965
        span = end_block - start_block
        assert span == 100_800                       # votingPeriod() kontraktu
        assert span * L1_BLOCK_SECONDS == 14 * 86_400  # dokładnie 14 dni

    def test_bloki_startu_sa_z_ethereum_nie_z_arbitrum(self):
        """Kontrola rzędu wielkości - gdyby ktoś kiedyś przeliczał je węzłem
        Arbitrum, ten test ma przypomnieć dlaczego nie wolno. Zdarzenie stoi
        w bloku L2 rzędu 483 mln, a niesie startBlock rzędu 25 mln."""
        blok_l2_zdarzenia = 483_508_532
        start_block_l1 = 25_547_165
        assert start_block_l1 * 10 < blok_l2_zdarzenia


class TestOknaSkanowania:
    @pytest.mark.asyncio
    async def test_zakres_dzielony_na_okna(self):
        """Publiczne węzły odmawiają szerokich zakresów - stąd podział."""
        from app.services.governor_client import SCAN_WINDOW_BLOCKS
        zakresy = []

        class Klient:
            async def post(self, url, json=None, **k):
                zakresy.append((int(json["params"][0]["fromBlock"], 16),
                                int(json["params"][0]["toBlock"], 16)))
                class R:
                    status_code = 200
                    def json(self_inner): return {"result": []}
                return R()

        klient = GovernorClient(endpoints=["https://x"])
        start, koniec = 1000, 1000 + SCAN_WINDOW_BLOCKS * 2 + 5
        await klient._logs(Klient(), ["0xtopic"], start, koniec)
        assert len(zakresy) == 3
        assert zakresy[0][0] == start
        assert zakresy[-1][1] == koniec
        # okna nie mogą się nakładać ani zostawiać dziur
        for (_, k1), (p2, _) in zip(zakresy, zakresy[1:]):
            assert p2 == k1 + 1
