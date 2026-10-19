"""Canonical Arbitrum proposal record from arbdata.com (Entropy Advisors).

<!-- catalog-read --> checked app/services: snapshot_client, tally_client and
governor_client all read votes; none carries an authoritative proposal registry
with voting windows.

Why this exists
---------------
A delegate pointed at this source during a research session: it is what the DAO
itself uses. Two things it settles that the contract scan cannot.

1. REAL VOTING WINDOWS. `ProposalCreated` carries startBlock and endBlock as
   ETHEREUM block numbers, so governor_client reconstructs the window
   arithmetically at 12 s per block. Checked against ArbOS61: the arithmetic
   ends the vote on 2026-07-30, the registry says 2026-08-01. Two days off, and
   the error grows with the voting period. Concurrency asks whether decisions
   overlapped, so a two-day error moves real counts.

2. COVERAGE. The registry holds 89 proposals across two governors - 31 core and
   58 treasury. governor_client scans the core contract only, so two thirds of
   the DAO's proposals are invisible to the index. A delegate voting on treasury
   business carries load that the measurement cannot see.

`proposal_id` is the same integer that governor_client decodes from the event
payload, so the join needs no mapping table.

What this is NOT
----------------
Not a vote source. It says which proposals existed and when they were open; who
voted still comes from Snapshot and from the chain. Treasury VOTES additionally
need a scan of the treasury governor contract, which this module does not do.

A third party can go stale exactly the way Tally did, and a stale registry
answers HTTP 200 like a fresh one. `freshest()` exposes the newest record so a
caller can compare it against what the chain reports rather than trusting the
response code.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx

from app.services.fatigue_engine import (
    SourceReceipt, HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, UNAVAILABLE, ERROR,
    COV_PARTIAL_DATA,
)


def _najnowszy_rekord(rows) -> Optional[int]:
    """Znacznik czasu najnowszej propozycji w rejestrze (D5=A, 11.09).

    Dowodem pokrycia dla zrodla oddajacego caly zbior jednym zadaniem nie jest liczba stron -
    ta jest zawsze jedna - tylko ZAKRES, jaki zbior obejmuje. Rejestr odpowiada kompletnie
    i jednoczesnie urywa sie na 2026-08-17 (pomiar 11.09: 90 rekordow, najnowszy sprzed
    25 dni), wiec "dostalismy calosc" i "calosc siega mierzonej chwili" to dwa rozne zdania.

    Brak pola czasu w rekordach daje `None`, czyli "nie zmierzono" - inny stan niz zero.
    """
    czasy = []
    for r in rows or []:
        v = (r or {}).get("creation_time")
        if v in (None, ""):
            continue
        try:
            czasy.append(int(v) if str(v).isdigit() else int(
                dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()))
        except (ValueError, TypeError):
            continue
    return max(czasy) if czasy else None

# Where the registry lives since arbdata.com moved to the Entropy Data platform. Measured on
# 2026-10-19: the old `https://arbdata.com/api/governance-proposals` answers 406 to
# `Accept: application/json` and 404 (a Next.js page) to `*/*`. The governance page renders a
# table widget whose rows come from the chart data route below, fetched in two steps the
# way the site's own script does it: the public site config hands out a short-lived
# `data_key`, and the chart route refuses without it (403 `data_key_invalid`).
#
# The chart carries the same 90 records with identical title, category, theme, type, windows
# and outcome as the last copy of the old endpoint (2026-09-16), but NOT the on-chain
# `proposal_id`, `governor` or `proposer_name` - only `proposal_number`. The on-chain id is the
# join key for windows and categories in governor_client, so it is restored from
# `KEYS_PATH`, a frozen map built from that copy, never computed on the fly.
SITE_ENDPOINT = "https://api.entropydata.co/public/sites/arbdata.com"
CHART_ID = "c6e84e4d-6a96-429d-9e29-ea404ea10e15"
ENDPOINT = f"{SITE_ENDPOINT}/charts/{CHART_ID}/data"
# The site script asks for at most 1e5 rows per page (RESULTS_MAX_PAGE_LIMIT); the server caps
# the page further by cell count. Completeness is proven by `row_count`, not by this number.
PAGE_LIMIT = 100_000
KEYS_PATH = Path(__file__).resolve().with_name("arbdata_proposal_keys.json")


class _Odmowa(Exception):
    """The registry answered, but with something the instrument must not accept."""

# The 403 recorded on 2026-09-04 was NOT a withdrawn permission - it was a bot filter.
# Measured on 2026-09-08: the same URL answers 403 to a bare client and 200 with a browser
# User-Agent plus Referer, returning all 90 records with the taxonomy intact. The earlier
# reading ("registry gone, every per-event measurement NOT_ELIGIBLE, ask Entropy Advisors
# for access") diagnosed a permission problem from a status code. A status code names the
# refusal, never its reason - the same class of error as reading `auth-test` as proof that
# an account may post.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Referer": "https://arbdata.com/",
    "Accept": "application/json",
}

# Last good copy of the registry. Taxonomy does not change for past proposals,
# so a cached registry answers correctly for everything it covers and is
# reported PARTIAL (dated) rather than pretending to be live. Found necessary
# on 2026-09-04: the endpoint started answering 403 {"error":"Forbidden"} and
# the novelty component silently fell back to the keyword list for everyone.
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "arbdata-registry.json"


def _klucz(title: str) -> str:
    """Tytul sprowadzony do postaci porownywalnej miedzy zrodlami - nawiasy,
    przedrostek `Constitutional AIP:`, znaki ucieczki i wielkosc liter."""
    # UWAGA: te wzorce mialy podwojne ukosniki (r"\\b" zamiast r"\b"), przez co w raw
    # stringu znaczyly literalny backslash plus litere - czyli nie pasowaly do niczego.
    # Skutek byl CICHY: `_klucz` zwracalo tytul z przedrostkiem i niezwinietymi spacjami,
    # dopasowanie po tytule trafialo wylacznie przy znaku w znak identycznym zapisie,
    # a `novelty` liczylo sie z historii bez kategorii przy czystym pokwitowaniu.
    # Wykryte 2026-09-08 w przegladzie kodu.
    t = (title or "").lower()
    t = t.replace("\\", "")
    t = re.sub(r"[\[\]()]", " ", t)
    t = re.sub(r"\b(constitutional|non-constitutional|aip|proposal)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tekst(v) -> str:
    """Wartosc pola do porownania z kopia: brak i pusty napis to ten sam stan."""
    return "" if v is None else str(v)


def _epoch(stamp: Optional[str]) -> Optional[int]:
    """`2026-07-27 15:30:07` -> epoch. The registry publishes UTC without a zone
    marker; a naive parse would take the server's local zone and shift windows
    by whole hours."""
    if not stamp:
        return None
    try:
        naive = dt.datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
        return int(naive.replace(tzinfo=dt.timezone.utc).timestamp())
    except (ValueError, TypeError):
        return None


class ArbdataClient:
    """Proposal registry keyed by the on-chain proposal id."""

    def __init__(self, endpoint: str = ENDPOINT, cache_path: Path = CACHE_PATH,
                 site_endpoint: str = SITE_ENDPOINT, keys_path: Path = KEYS_PATH):
        self.endpoint = endpoint
        self.site_endpoint = site_endpoint
        self.keys_path = Path(keys_path)
        self.cache_path = Path(cache_path)
        # Records of the live answer that the frozen key map does not know: a coverage
        # gap (no on-chain id = no window, no category join), counted in the receipt.
        self._luki: list = []
        self._rekordy: Dict[int, dict] = {}
        self._po_tytule: Optional[Dict[str, str]] = None
        # Capability receipt of the last load() (closure review point 2). The
        # registry is a SOURCE the instrument depends on - novelty is defined on
        # the DAO's taxonomy - so its failure has to reach the eligibility
        # verdict, not just stdout.
        self.receipt: SourceReceipt = SourceReceipt("taxonomy", UNAVAILABLE, detail="not loaded")

    async def load(self) -> int:
        """Fetch the registry. Returns how many proposals were read and sets
        `self.receipt`.

        Live answer -> HEALTHY_COMPLETE (or HEALTHY_EMPTY), and the rows are
        written to the cache. No live answer -> the cached copy, if any, with
        PARTIAL and the cache date in the detail; without a cache the receipt is
        ERROR (HTTP status / bad shape) or UNAVAILABLE (transport). The index is
        left empty in that last case, so callers fall back to whatever they had -
        and the verdict says so. Silence here must not look like "no proposals
        exist"; that confusion is what let a frozen Tally hide six real votes.
        """
        failure: Optional[SourceReceipt] = None
        rows = None
        self._luki = []
        try:
            async with httpx.AsyncClient(headers=BROWSER_HEADERS, follow_redirects=True) as client:
                rows = self._odtworz(await self._pobierz(client), self._wczytaj_klucze())
        except _Odmowa as e:
            print(f"❌ arbdata refused: {e}")
            failure = SourceReceipt("taxonomy", ERROR, detail=str(e)[:200])
        except httpx.HTTPStatusError as e:
            print(f"❌ arbdata HTTP {e.response.status_code}: {e}")
            failure = SourceReceipt("taxonomy", ERROR, detail=f"HTTP {e.response.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"❌ arbdata unreachable: {e}")
            failure = SourceReceipt("taxonomy", UNAVAILABLE, detail=f"{type(e).__name__}: {e}"[:200])
        if failure is None and not isinstance(rows, list):
            print("❌ arbdata returned an unexpected shape - index left empty")
            failure = SourceReceipt("taxonomy", ERROR, detail="unexpected shape")

        if failure is None:
            self._index(rows)
            self._write_cache(rows)
            # DOWOD POKRYCIA (D5=A, 11.09). Do tej daty `coverage_state` dla tego zrodla
            # powstawal z rzutu `state`, a `page_count` i `limit_hit` byly `None`, czyli
            # NIE ZMIERZONE - a mimo to kwalifikacja czytala COMPLETE. Komentarz przy polach
            # pokwitowania mowil wprost, ze `None` nie wolno czytac jako dowodu kompletnosci.
            #
            # Co jest dowodem dla TEGO zrodla: rejestr przychodzi CALY jedna strona danych
            # wykresu, a `_pobierz` sprawdza, ze liczba wierszy rowna sie `row_count`
            # deklarowanemu przez serwer - strona krotsza konczy sie odmowa, nie cisza.
            # Stad `page_count=1` i `limit_hit=False` sa POMIAREM tego wywolania, nie
            # zalozeniem o API.
            #
            # Odrzucenie czesci wierszy przy indeksowaniu jest luka POKRYCIA, nie dostepnosci:
            # zrodlo oddalo komplet, ale instrument uzyl mniej, niz dostal. Ta sama klasa
            # obejmuje rekordy bez wpisu w mapie kluczy (19.10): bez identyfikatora on-chain
            # nie maja okna ani kategorii dla zdarzen z kontraktu, wiec ida do pokwitowania
            # jako rekordy bez okna, z czasem najnowszego - jak `unknown_window_newest_at`
            # u klientow glosow.
            odrzucone = len(rows) - len(self._rekordy)
            luki = len(self._luki)
            wszystkie = len(rows) + luki
            opis = []
            if odrzucone:
                opis.append(f"{odrzucone} z {wszystkie} rekordow rejestru nie weszlo do indeksu")
            if luki:
                opis.append(f"{luki} z {wszystkie} rekordow bez wpisu w mapie kluczy on-chain "
                            f"({self.keys_path.name})")
            self.receipt = SourceReceipt(
                "taxonomy", HEALTHY_COMPLETE if self._rekordy else HEALTHY_EMPTY,
                events=len(self._rekordy),
                taxonomy_snapshot_id=self.snapshot_id(rows),
                page_count=1, record_count=wszystkie, limit_hit=False,
                newest_record_at=_najnowszy_rekord(rows),
                unknown_window=luki,
                # `_epoch`, nie `_najnowszy_rekord`: rejestr podaje UTC bez znacznika strefy,
                # a `_najnowszy_rekord` parsuje taki zapis w strefie serwera (o dwie godziny
                # obok na mozgu). Tamtej funkcji tu nie poprawiam - jej wynik siedzi
                # w `newest_record_at` kazdego zapisanego manifestu.
                unknown_window_newest_at=max(
                    (c for c in (_epoch(r.get("creation_time")) for r in self._luki) if c),
                    default=None) if luki else None,
                coverage_state=COV_PARTIAL_DATA if (odrzucone or luki) else "",
                detail="; ".join(opis))
            return len(self._rekordy)

        cached, stamp = self._read_cache()
        if cached is not None:
            self._index(cached)
            self.receipt = SourceReceipt(
                "taxonomy", PARTIAL, events=len(self._rekordy),
                taxonomy_snapshot_id=self.snapshot_id(cached, stamp),
                page_count=1, record_count=len(cached), limit_hit=False,
                newest_record_at=_najnowszy_rekord(cached),
                detail=f"live: {failure.detail}; cached copy from {stamp}")
            print(f"⚠ arbdata: using cached registry from {stamp} ({len(self._rekordy)} rows)")
            return len(self._rekordy)
        self.receipt = failure
        return 0

    async def _klucz_danych(self, client) -> str:
        """`data_key` z publicznej konfiguracji strony - wydawany przy kazdym odczycie."""
        r = await client.get(self.site_endpoint, timeout=45.0)
        r.raise_for_status()
        try:
            klucz = (r.json() or {}).get("data_key")
        except (ValueError, AttributeError):
            klucz = None
        if not isinstance(klucz, str) or not klucz:
            raise _Odmowa("site config without data_key")
        return klucz

    async def _pobierz(self, client) -> dict:
        """Strona danych wykresu. Odmowa klucza (403) dostaje JEDNO ponowienie ze swiezym
        kluczem - klucz jest krotkotrwaly, wiec 403 bywa jego wygasnieciem, nie odmowa
        dostepu. Drugie 403 przechodzi wyzej jako blad HTTP."""
        for proba in range(2):
            klucz = await self._klucz_danych(client)
            r = await client.get(self.endpoint, timeout=45.0, params={
                "limit": str(PAGE_LIMIT), "offset": "0", "key": klucz})
            if r.status_code == 403 and proba == 0:
                print("⚠ arbdata: data_key refused (403), retrying once with a fresh key")
                continue
            r.raise_for_status()
            break
        try:
            dane = r.json()
        except ValueError:
            raise _Odmowa("chart data is not JSON")
        if not isinstance(dane, dict) or not isinstance(dane.get("rows"), list) \
                or not isinstance(dane.get("columns"), list):
            raise _Odmowa("unexpected shape: no columns/rows")
        # Dowod kompletnosci tej strony: serwer deklaruje liczbe wierszy zbioru wynikow.
        if dane.get("row_count") != len(dane["rows"]):
            raise _Odmowa(f"page truncated: {len(dane['rows'])} rows of "
                          f"row_count {dane.get('row_count')}")
        return dane

    def _wczytaj_klucze(self) -> dict:
        try:
            dane = json.loads(self.keys_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise _Odmowa(f"proposal key map unreadable: {type(e).__name__}")
        if not isinstance(dane.get("keys"), dict) or not dane.get("frozen_fields"):
            raise _Odmowa("proposal key map without keys/frozen_fields")
        return dane

    def _odtworz(self, dane: dict, mapa: dict) -> list:
        """Wiersze-tablice -> rekordy w ksztalcie dawnego rejestru, z kluczem on-chain z mapy.

        Kolumny mapowane sa PO NAZWIE z `columns`, nigdy po pozycji. Rekord z mapy, ktorego
        tresc rozni sie od zamrozonej kopii w ktorymkolwiek polu czytanym przez instrument,
        przerywa caly odczyt: zmiana po stronie zrodla wymaga przegladu, a przyjeta po cichu
        zmienilaby historyczne wyniki pod tym samym `measurement_id`. Rekord spoza mapy jest
        luka pokrycia (`self._luki`), nie bledem - nowa propozycja to nie zmiana starej.
        """
        nazwy = [c.get("name") if isinstance(c, dict) else None for c in dane["columns"]]
        pola = list(mapa["frozen_fields"])
        brak = [n for n in ["proposal_number"] + pola if n not in nazwy]
        if brak:
            raise _Odmowa(f"unexpected shape: missing columns {','.join(brak)}")
        klucze = mapa["keys"]
        rows, rozjazdy = [], []
        for w in dane["rows"]:
            if not isinstance(w, list) or len(w) != len(nazwy):
                raise _Odmowa("unexpected shape: row width differs from columns")
            rec = dict(zip(nazwy, w))
            try:
                nr = str(int(str(rec.get("proposal_number"))))
            except (TypeError, ValueError):
                raise _Odmowa("unexpected shape: proposal_number not an integer")
            wpis = klucze.get(nr)
            if wpis is None:
                self._luki.append(rec)
                continue
            zamrozone = wpis.get("frozen") or {}
            inne = [p for p in pola if _tekst(rec.get(p)) != _tekst(zamrozone.get(p))]
            if inne:
                rozjazdy.append(f"#{nr}: {','.join(inne)}")
                continue
            rec["proposal_id"] = wpis["proposal_id"]
            rec["governor"] = wpis.get("governor")
            rec["proposer_name"] = wpis.get("proposer_name")
            rows.append(rec)
        if rozjazdy:
            raise _Odmowa(f"content drift vs frozen copy ({len(rozjazdy)} records): "
                          + "; ".join(rozjazdy[:5]))
        return rows

    @staticmethod
    def snapshot_id(rows, stamp: Optional[str] = None) -> str:
        """Identyfikator ZAMROZONEGO zbioru kategorii, ktory zbudowal pomiar (P6, 11.09).

        Rejestr zyje: kategoria dopisana po pomiarze zmienilaby historyczny wynik przy
        ponownym liczeniu, a pomiar nie mialby jak tego pokazac. Identyfikator wiaze wynik
        z konkretna TRESCIA rejestru, nie z data odczytu - dwa odczyty tego samego zbioru
        daja ten sam identyfikator, a dopisanie jednej kategorii zmienia go.

        Skrot liczy sie z pary (identyfikator propozycji, kategoria) po sortowaniu, wiec
        kolejnosc odpowiedzi serwisu na niego nie wplywa - ta sama zasada, ktora obowiazuje
        cale wejscie kanoniczne od 10.09.
        """
        pary = sorted(
            (str(r.get("proposal_id")), str(r.get("proposal_category") or ""))
            for r in (rows or [])
        )
        skrot = hashlib.sha256(
            json.dumps(pary, ensure_ascii=False).encode()).hexdigest()[:16]
        data = (stamp or dt.datetime.now(dt.timezone.utc).date().isoformat())[:10]
        return f"tax:{skrot}@{data}"

    def _index(self, rows) -> None:
        for row in rows:
            try:
                pid = int(str(row.get("proposal_id")))
            except (TypeError, ValueError):
                continue
            self._rekordy[pid] = row

    def _write_cache(self, rows) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "endpoint": self.endpoint,
                "rows": rows,
            }))
        except OSError as e:
            print(f"⚠ arbdata cache not written: {e}")

    def _read_cache(self):
        try:
            data = json.loads(self.cache_path.read_text())
            return data.get("rows") or [], (data.get("fetched_at") or "?")[:10]
        except (OSError, ValueError):
            return None, None

    def window(self, proposal_id: int) -> Optional[Tuple[int, int]]:
        """Real (opens, closes) for a proposal, or None when unknown.

        None means "this registry does not cover it", never "it had no window".
        Callers must keep those apart: an absent window has to drop out of
        concurrency explicitly, not be counted as an overlap that did not happen.
        """
        row = self._rekordy.get(proposal_id)
        if not row:
            return None
        opens = _epoch(row.get("creation_time"))
        closes = _epoch(row.get("voting_end_time"))
        if opens is None or closes is None or closes <= opens:
            return None
        return opens, closes

    def subject(self, proposal_id: int) -> Optional[Tuple[str, str]]:
        """What the proposal is ABOUT: (category, theme) as the DAO classifies it.

        The registry carries 12 categories - Grants 20, Network Changes 18, DAO
        Operations 16, Incentives 7, DAO Amendments 6, Incident Response 1 among
        them - plus a finer theme on part of the set.

        Two uses, both open rather than wired in.

        First, it answers a question the measurement could not: we read how long
        a proposal is and how many arrived at once, and knew nothing about what
        delegates were deciding. A workload claim that cannot say whether the
        week held an emergency or four routine grant renewals is thin.

        Second, `novelty` currently matches a keyword list of ours against the
        title and body, and scores 0.0 for every Phase A participant. A taxonomy
        the DAO maintains is a better basis for "is this a familiar kind of
        decision" than words we picked ourselves - but swapping it changes the
        instrument, so it needs a decision and a journal entry, not a quiet edit.
        """
        row = self._rekordy.get(proposal_id)
        if not row:
            return None
        return (row.get("proposal_category") or "", row.get("proposal_theme") or "")

    def kategoria_po_tytule(self, title: str) -> Optional[str]:
        """Kategoria dopasowana po TYTULE, dla zrodel bez identyfikatora on-chain.

        Snapshot nadaje propozycjom wlasne identyfikatory, wiec zlaczenie po
        `proposal_id` obejmuje wylacznie zdarzenia z kontraktu. Bez dopasowania po
        tytule kategorie mialaby garstka propozycji, a skladnik liczony z takiej
        historii zwracalby zero i wygladalby na dzialajacy.
        """
        k = _klucz(title)
        if not k:
            return None
        if self._po_tytule is None:
            self._po_tytule = {}
            for row in self._rekordy.values():
                kk = _klucz(row.get("proposal_title") or "")
                if kk and row.get("proposal_category"):
                    self._po_tytule[kk] = row["proposal_category"]
        return self._po_tytule.get(k)

    def przypisz_kategorie(self, votes) -> int:
        """Dokleja `category` tam, gdzie jej brak. Zwraca liczbe uzupelnien."""
        ile = 0
        for v in votes:
            if getattr(v, "category", None):
                continue
            kat = self.kategoria_po_tytule(getattr(v, "title", "") or "")
            if kat:
                v.category = kat
                ile += 1
        return ile

    def governor(self, proposal_id: int) -> Optional[str]:
        """`core` or `treasury`. Lets a caller report how much of the DAO's
        business its vote sources actually reach."""
        row = self._rekordy.get(proposal_id)
        return row.get("governor") if row else None

    def freshest(self) -> Optional[int]:
        """Creation time of the newest proposal in the registry.

        Freshness is checked by the date of the newest record, not by the status
        code - a frozen dataset answers 200 exactly like a live one, which is how
        Tally's Arbitrum index went stale unnoticed for two months.
        """
        czasy = [_epoch(r.get("creation_time")) for r in self._rekordy.values()]
        czasy = [c for c in czasy if c]
        return max(czasy) if czasy else None

    def __len__(self) -> int:
        return len(self._rekordy)
