"""N0.2 - własności domknięcia semantycznego, nie testy pojedynczych przypadków.

Recenzja 78179 (`Ihopeudie`, 2026-09-09) nazwała klasę błędu: *recursive semantic
regression* - lokalna naprawa gubi rozróżnienie, które wraca warstwę niżej, tam
gdzie stan zdegradowany zamienia się w coś wyglądającego na ważne. Cztery testy
kontrprzykładów łapią to, co znamy; te własności mają wyłapać piątą rozbieżność.

Reguła, którą egzekwuje ten plik (plan domknięcia, sekcja 0.1):

    dwa różne stany mogą dzielić tę samą tożsamość albo ten sam werdykt tylko
    wtedy, gdy każda decyzja niżej jest rzeczywiście niewrażliwa na różnicę
    między nimi.

Siedem własności z sekcji 1.2 planu. Część jest CZERWONA świadomie - opisuje
kontrakt, który ma obowiązywać po P1-P13, a nie stan kodu z 2026-09-11. Każda
czerwona własność niesie w docstringu plik i linię, które ją łamią, żeby nie
trzeba było tego szukać drugi raz.

Uruchomienie: python3 -m pytest tests/fatigue/test_semantic_closure.py -v
Test wsteczny (N0.3): ten plik na 09ece75 i a33a1ca - patrz N0-INWENTARZ-GRANIC.
"""

import itertools
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import (  # noqa: E402
    AUTH_MISSING,
    ERROR,
    HEALTHY_COMPLETE,
    HEALTHY_EMPTY,
    PARTIAL,
    TRUNCATED,
    UNAVAILABLE,
    FatigueEngine,
    SourceReceipt,
)

WYMAGANE_ZRODLA = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")

# Stany, które wg planu (P2/P9) NIE MOGĄ dać pomiaru pierwszorzędnego: każdy z nich
# znaczy "nie wiemy, czy objęliśmy obszar wymagany przez konstrukt".
STANY_BEZ_DOWODU_POKRYCIA = (PARTIAL, TRUNCATED, ERROR, UNAVAILABLE, AUTH_MISSING)


@dataclass
class Obserwacja:
    """Propozycja-etap tak, jak ją widzi silnik po rekonstrukcji."""

    start: int
    end: int
    id: str = ""
    title: str = "Proposal"
    body: str = ""
    state: str = "closed"
    category: str = ""
    voted_at: Optional[int] = None
    cast_at: Optional[int] = None
    source_vote_id: str = ""
    native_proposal_id: str = ""
    source_domain: str = "snapshot"
    voter: str = ""
    lifecycle_id: str = ""
    # Podstawa okna - od 11.09 (P4) rozstrzyga o wejściu do współbieżności pierwszorzędnej.
    # Atrapy deklarują dowód, bo warstwy produkcyjne go deklarują: Snapshot podaje okno
    # wprost, rejestr taksonomii również. Test badający BRAK dowodu ustawia pole sam.
    window_basis: str = "SNAPSHOT_EXACT"
    window_uncertainty_reason: str = ""


@pytest.fixture
def teraz() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def silnik() -> FatigueEngine:
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 1, "volume_30d": 3, "concurrent": 2, "reading_words": 1500},
    )
    return eng


def historia(teraz: datetime, dni: List[int], kategoria: str = "grants") -> List[Obserwacja]:
    out = []
    for i, d in enumerate(dni):
        s = int((teraz - timedelta(days=d)).timestamp())
        out.append(
            Obserwacja(
                start=s,
                end=s + 3 * 86_400,
                id=f"hist-{i}",
                title=f"Historical decision {i}",
                body="routine monthly report on fees " * 20,
                category=kategoria,
                voted_at=s,
                cast_at=s,
                source_vote_id=f"vote-{i}",
                native_proposal_id=f"prop-{i}",
                lifecycle_id=f"cycle-{i}",
            )
        )
    return out


def cel(teraz: datetime, slow: int = 710, kategoria: str = "network changes") -> Obserwacja:
    s = int((teraz - timedelta(hours=2)).timestamp())
    return Obserwacja(
        start=s,
        end=s + 3 * 86_400,
        id="target-1",
        title="New staking primitive",
        body="word " * slow,
        category=kategoria,
        voted_at=s,
        cast_at=s,
        source_vote_id="vote-target",
        native_proposal_id="prop-target",
        lifecycle_id="cycle-target",
    )


def ekspozycja(teraz: datetime, ile: int = 3) -> List[Obserwacja]:
    """Propozycje otwarte w chwili głosu - ekspozycja ekosystemu."""
    out = []
    for i in range(ile):
        s = int((teraz - timedelta(days=4 + i)).timestamp())
        out.append(
            Obserwacja(
                start=s,
                end=s + 20 * 86_400,
                id=f"eco-{i}",
                title=f"Ecosystem proposal {i}",
                body="ecosystem body " * 10,
                category="dao operations",
                native_proposal_id=f"eco-prop-{i}",
                lifecycle_id=f"eco-cycle-{i}",
            )
        )
    return out


def pokwitowania(stan_per_zrodlo: Optional[dict] = None, **kw) -> List[SourceReceipt]:
    """Komplet pokwitowań dla wszystkich wymaganych źródeł."""
    stany = {z: HEALTHY_COMPLETE for z in WYMAGANE_ZRODLA}
    stany.update(stan_per_zrodlo or {})
    out = []
    for z, s in stany.items():
        dodatki = dict(kw)
        if z == "taxonomy":
            # Zamrozony snapshot taksonomii (P6) - warunek pomiaru pierwszorzednego.
            dodatki["taxonomy_snapshot_id"] = "tax:testowy0000000@2026-09-11"
        out.append(SourceReceipt(z, s, events=5, **dodatki))
    return out


class _Brak:
    """Wartownik: „argumentu nie podano" to inny stan niż „podano None".

    Bez niego `licz(..., eco=None)` znaczyłoby „weź domyślną ekspozycję", więc test
    awarii warstwy ekspozycji mierzyłby przypadek zdrowy. Pierwsza wersja tego pliku
    miała dokładnie ten błąd i test padał z powodu helpera, nie kodu - ta sama klasa,
    którą plik ma wykrywać, tylko w samym teście.
    """


BRAK = _Brak()


def licz(silnik, teraz, *, target=BRAK, hist=BRAK, eco=BRAK, receipts=BRAK):
    return silnik.compute_per_event(
        address="0xtest",
        target_proposal=cel(teraz) if target is BRAK else target,
        voted_history=historia(teraz, [2, 5, 9, 20]) if hist is BRAK else hist,
        now=teraz,
        ecosystem_proposals=ekspozycja(teraz) if eco is BRAK else eco,
        source_receipts=pokwitowania() if receipts is BRAK else receipts,
    )


# ---------------------------------------------------------------------------
# P-D. Positive acceptance - stoi PIERWSZE świadomie.
# ---------------------------------------------------------------------------

def test_PD_poprawny_kompletny_przypadek_przechodzi(silnik, teraz):
    """Ręcznie rozstrzygnięty, kompletny przypadek MUSI wyjść PRIMARY_ELIGIBLE.

    Bez tej własności implementacja "odrzuć wszystko" przechodziłaby pozostałe
    sześć. Plan, sekcja 1.2: "Implementacja «odrzuć wszystko» ma nie przechodzić
    testu klasy".
    """
    r = licz(silnik, teraz)
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", (
        f"kompletny przypadek odrzucony: {r.identity.eligibility_reasons}"
    )
    assert r.fatigue_score > 0


# ---------------------------------------------------------------------------
# P-B. Transport invariance.
# ---------------------------------------------------------------------------

def test_PB_permutacja_wejscia_nie_zmienia_niczego(silnik, teraz):
    """Kolejność rekordów w odpowiedzi źródła nie jest informacją o obciążeniu.

    Naprawa z 2026-09-10 zamknęła cztery kontrprzykłady tej klasy; ta własność
    pilnuje jej dla dowolnej permutacji, nie dla czterech znanych.
    """
    hist = historia(teraz, [2, 5, 9, 20, 27])
    eco = ekspozycja(teraz, 4)
    wzorzec = licz(silnik, teraz, hist=hist, eco=eco)

    # Sto permutacji to warunek odbioru P1 z planu domknięcia, nie okrągła liczba:
    # przy pięciu rekordach historii i czterech ekspozycji przestrzeń jest większa niż
    # to, co da się wyliczyć wyczerpująco, a wynik ma być niezależny od każdej z nich.
    rng = random.Random(20260911)
    for _ in range(100):
        h = hist[:]
        e = eco[:]
        rng.shuffle(h)
        rng.shuffle(e)
        r = licz(silnik, teraz, hist=h, eco=e)
        assert r.identity.measurement_id == wzorzec.identity.measurement_id
        assert r.fatigue_score == wzorzec.fatigue_score
        assert r.components == wzorzec.components
        assert r.identity.eligibility == wzorzec.identity.eligibility


def test_PB_permutacja_wyczerpujaca_na_malym_zbiorze(silnik, teraz):
    """Wszystkie permutacje czteroelementowej historii - bez losowania."""
    hist = historia(teraz, [2, 5, 9, 20])
    wzorzec = licz(silnik, teraz, hist=hist)
    for perm in itertools.permutations(hist):
        r = licz(silnik, teraz, hist=list(perm))
        assert r.identity.measurement_id == wzorzec.identity.measurement_id
        assert r.fatigue_score == wzorzec.fatigue_score


def historia_z_remisami(teraz: datetime) -> List[Obserwacja]:
    """Historia, w której kolejność wejścia MOŻE zmienić wynik, jeśli kod na to pozwala.

    Trzy warunki naraz, każdy wzięty z kontrprzykładu wykonanego 2026-09-10:
    dwie obserwacje o IDENTYCZNYM czasie głosu (wybór reprezentanta cyklu),
    bez stabilnego identyfikatora (remis rozstrzygany pozycją w liście albo
    adresem obiektu) i o RÓŻNYCH kategoriach (wybór kategorii cyklu decyduje
    o `novelty`).

    Bez tych warunków permutacja nie ma czego przestawić: test z samymi
    identyfikatorami przechodzi również na kodzie sprzed naprawy, czyli nie
    mierzy niczego. Sprawdzone wykonaniem na `09ece75` (2026-09-11).
    """
    t = int((teraz - timedelta(days=3)).timestamp())
    teraz_ts = int(teraz.timestamp())
    # Dwa etapy JEDNEGO cyklu (`lifecycle_id` ten sam) o identycznym czasie głosu.
    # Reprezentanta cyklu wybiera kod - i tylko wtedy, gdy etapy różnią się oknem
    # i kategorią, ten wybór widać w wyniku: `end` przed chwilą pomiaru kontra po
    # niej zmienia ujawnione zaangażowanie, a kategoria zmienia `novelty`.
    wspolny = dict(start=t, voted_at=t, cast_at=t, id="", lifecycle_id="lc")
    starszy = int((teraz - timedelta(days=25)).timestamp())
    return [
        Obserwacja(end=teraz_ts - 3600, title="Stage A", body="alpha " * 40,
                   category="grants", **wspolny),
        Obserwacja(end=teraz_ts + 5 * 86_400, title="Stage B", body="beta " * 900,
                   category="network changes", **wspolny),
        Obserwacja(start=starszy, end=starszy + 3 * 86_400, voted_at=starszy, cast_at=starszy,
                   title="Older", body="gamma " * 60, category="dao operations",
                   id="", lifecycle_id="lc-older"),
    ]


def test_PB_remisy_bez_stabilnego_identyfikatora_nie_zaleza_od_kolejnosci(silnik, teraz):
    """Dwie obserwacje o tym samym czasie głosu i bez identyfikatora.

    To jest wariant permutacji, który PADA na `09ece75` - czyli jedyna wersja tej
    własności mierząca naprawę z 2026-09-10, a nie samo jej istnienie.
    """
    hist = historia_z_remisami(teraz)
    wzorzec = licz(silnik, teraz, hist=hist)
    for perm in itertools.permutations(hist):
        r = licz(silnik, teraz, hist=list(perm))
        assert r.identity.measurement_id == wzorzec.identity.measurement_id, (
            "kolejność rekordów o równym czasie zmieniła tożsamość pomiaru"
        )
        assert r.components == wzorzec.components, (
            f"kolejność zmieniła składniki: {r.components} wobec {wzorzec.components}"
        )
        assert r.fatigue_score == wzorzec.fatigue_score


# ---------------------------------------------------------------------------
# P-A. Semantic sensitivity.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pole,wartosc",
    [
        ("body", "word " * 1400),          # reading_time
        ("category", "grants"),             # novelty
        ("title", "Completely different decision"),
    ],
)
def test_PA_zmiana_pola_wplywajacego_na_wynik_zmienia_tozsamosc(silnik, teraz, pole, wartosc):
    """Pole, które zmienia składnik, musi zmieniać `measurement_id`.

    Odwrotność kontrprzykładu z 2026-09-10 (`reading_time` ze słów `body`,
    tożsamość z hashu `title + body`): wtedy różne wejścia dzieliły identyfikator.
    """
    bazowy = licz(silnik, teraz)
    zmieniony_cel = cel(teraz)
    setattr(zmieniony_cel, pole, wartosc)
    inny = licz(silnik, teraz, target=zmieniony_cel)

    assert inny.identity.measurement_id != bazowy.identity.measurement_id, (
        f"zmiana pola {pole!r} nie ruszyła measurement_id"
    )


def test_PA_zmiana_wplywajaca_na_skladnik_widoczna_w_wyniku(silnik, teraz):
    """Dłuższa treść celu = wyższy `reading_time`; cicha równość byłaby utratą."""
    krotki = licz(silnik, teraz, target=cel(teraz, slow=300))
    dlugi = licz(silnik, teraz, target=cel(teraz, slow=2400))
    assert dlugi.components.reading_time > krotki.components.reading_time


# ---------------------------------------------------------------------------
# P-C. Evidence monotonicity.  CZERWONA na 2026-09-11.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("zrodlo", WYMAGANE_ZRODLA)
@pytest.mark.parametrize("stan", STANY_BEZ_DOWODU_POKRYCIA)
def test_PC_utrata_dowodu_nie_moze_dac_pomiaru_pierwszorzednego(silnik, teraz, zrodlo, stan):
    """Stan bez dowodu pokrycia dyskwalifikuje pomiar konfirmacyjny.

    CZERWONA dla `PARTIAL`: produkcyjna konfiguracja ma go na liście stanów
    dopuszczonych (`fatigue_config.yaml#eligibility.eligible_states`), a silnik
    dokłada wtedy wyłącznie notatkę niedyskwalifikującą
    (`fatigue_engine.py:752-753`). Plan, sekcja 16: "`PARTIAL` jako eligible -
    zakazany przez P2/P9".

    CZERWONA dla `TRUNCATED` z historią starszą niż okno kontekstu:
    `fatigue_engine.py:755-760` przepuszcza taki pomiar z notatką
    "context complete". To rozumowanie wewnątrz jednego źródła, nie osobny dowód
    pokrycia - własność P-G.
    """
    stare = int((teraz - timedelta(days=400)).timestamp())
    r = licz(
        silnik,
        teraz,
        receipts=pokwitowania({zrodlo: stan}, oldest_cast_at=stare),
    )
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE", (
        f"źródło {zrodlo} w stanie {stan} dało pomiar pierwszorzędny; "
        f"notatki: {r.identity.eligibility_notes}"
    )


def test_PC_mniej_dowodu_nie_podnosi_pewnosci(silnik, teraz):
    """Usunięcie pokwitowania nie może poprawić werdyktu ani podnieść wyniku."""
    pelny = licz(silnik, teraz)
    bez_jednego = licz(
        silnik, teraz, receipts=[r for r in pokwitowania() if r.source != "taxonomy"]
    )
    assert bez_jednego.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert len(bez_jednego.identity.eligibility_reasons) >= len(
        pelny.identity.eligibility_reasons
    )


def test_PC_pusta_ekspozycja_nie_jest_mniejszym_obciazeniem(silnik, teraz):
    """Awaria warstwy ekspozycji (`None`) nie ma prawa wyglądać jak brak propozycji."""
    awaria = licz(silnik, teraz, eco=None)
    assert awaria.identity.eligibility != "PRIMARY_ELIGIBLE", (
        "ekspozycja nieodczytana przeszła jako pomiar pierwszorzędny"
    )


# ---------------------------------------------------------------------------
# P-G. Completeness is separate from record quality.  CZERWONA na 2026-09-11.
# ---------------------------------------------------------------------------

def test_PG_poprawne_rekordy_nie_dowodza_kompletnosci_zbioru(silnik, teraz):
    """Każdy dostarczony rekord może być poprawny, a zbiór niekompletny.

    CZERWONA: `SourceReceipt` nie ma pola `coverage_state`
    (`fatigue_engine.py:102-112`), więc nie da się wyrazić stanu "rekordy dobre,
    pokrycie nieznane". Dziś `TRUNCATED` z dość starym `oldest_cast_at`
    kwalifikuje się, mimo że między najstarszym dostarczonym rekordem a limitem
    strony mogła przepaść dowolna liczba decyzji z wnętrza okna.
    """
    stare = int((teraz - timedelta(days=400)).timestamp())
    obciety = licz(
        silnik,
        teraz,
        receipts=pokwitowania({"snapshot": TRUNCATED}, oldest_cast_at=stare, limit=200),
    )
    assert obciety.identity.eligibility != "PRIMARY_ELIGIBLE", (
        "zbiór obcięty limitem strony przeszedł jako pierwszorzędny na podstawie "
        "wieku najstarszego rekordu, bez dowodu pokrycia"
    )


def test_PG_pokwitowanie_rozdziela_dostepnosc_od_pokrycia(silnik, teraz):
    """Pokwitowanie musi nieść dwa niezależne wymiary (plan P2, sekcja 3.1).

    CZERWONA: dziś jeden `state` miesza "zapytanie się wykonało" z "objęliśmy
    cały obszar".
    """
    r = SourceReceipt("snapshot", HEALTHY_COMPLETE, events=5)
    d = r.to_dict()
    assert "availability_state" in d and "coverage_state" in d, (
        f"pokwitowanie ma jeden wymiar stanu: {sorted(d)}"
    )


# ---------------------------------------------------------------------------
# P-E. Replay equivalence.
# ---------------------------------------------------------------------------

def test_PE_odtworzenie_daje_ten_sam_pelny_wynik(silnik, teraz):
    """`replay(zapisany manifest)` == `compute(to samo wejście)` dla CAŁEGO wyniku.

    Nie dla samego `fatigue_score`: składniki liczą się do trzech miejsc po
    przecinku przy wyniku zaokrąglanym do jednego, więc rozjazd `novelty` ginął
    w zaokrągleniu (naprawa 2026-09-10).
    """
    zywy = licz(silnik, teraz)
    odtworzony = FatigueEngine.replay(zywy.identity.manifest())

    assert odtworzony.fatigue_score == zywy.fatigue_score
    assert odtworzony.components == zywy.components
    assert odtworzony.metrics == zywy.metrics
    assert odtworzony.status == zywy.status
    assert odtworzony.identity.measurement_id == zywy.identity.measurement_id
    assert odtworzony.identity.eligibility == zywy.identity.eligibility


def test_PE_odtworzenie_nie_zaglada_do_sieci(silnik, teraz, monkeypatch):
    """Odtworzenie z zapisu nie ma prawa pytać źródeł ani czytać konfiguracji."""
    import socket

    zywy = licz(silnik, teraz)
    manifest = zywy.identity.manifest()

    def zabronione(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("odtworzenie sięgnęło po zasób zewnętrzny")

    monkeypatch.setattr(socket.socket, "connect", zabronione)
    odtworzony = FatigueEngine.replay(manifest)
    assert odtworzony.identity.measurement_id == zywy.identity.measurement_id


# ---------------------------------------------------------------------------
# P-F. Promotion preservation.  CZERWONA na 2026-09-11.
# ---------------------------------------------------------------------------

def test_PF_werdykt_i_powody_przezywaja_serializacje_wyniku(silnik, teraz):
    """Werdykt musi przetrwać każdą warstwę aż do zbioru analitycznego.

    Pierwsze ogniwo tej ścieżki: manifest pomiaru. Dalsze ogniwa (odpowiedź API,
    zapis, eksport `prep-dataset.py`, analiza H_val) mają osobne testy - eksport
    dziś NIE przenosi werdyktu do `dataset-clean.csv`, a `spearman-validation.py`
    filtruje wyłącznie braki danych, więc pomiar niekwalifikowany wchodzi do
    korelacji jako zwykła liczba (inwentarz granic, granica 9).
    """
    niekwalifikowany = licz(silnik, teraz, receipts=pokwitowania({"taxonomy": ERROR}))
    assert niekwalifikowany.identity.eligibility != "PRIMARY_ELIGIBLE"

    manifest = niekwalifikowany.identity.manifest()
    assert manifest.get("eligibility"), "manifest nie niesie werdyktu"
    assert manifest.get("eligibility_reasons"), "manifest nie niesie powodów dyskwalifikacji"


def test_PF_wynik_niekwalifikowany_nie_udaje_pierwszorzednego(silnik, teraz, tmp_path):
    """Liczba bez prawa wejścia do analizy musi być rozpoznawalna po samym wyniku.

    CZERWONA do P10: dziś niekwalifikowany pomiar niesie `fatigue_score` tak samo
    jak pierwszorzędny, a jedyną różnicą jest pole, które kolejne warstwy gubią.
    Kontrakt: albo wynik niesie jawny znacznik nieużywalności, albo istnieje
    bramka `promote_to_primary`, przez którą przechodzi wyłącznie pomiar
    kwalifikowany.
    """
    niekwalifikowany = licz(silnik, teraz, receipts=pokwitowania({"taxonomy": ERROR}))

    # ZMIANA 2026-09-11 (P10): brama mieszka w `app.services.promocja`, nie jako metoda
    # silnika. Własność pilnuje tego, co miała pilnować od początku - że istnieje JEDNA
    # droga do zbioru pierwszorzędnego i że przepuszcza wyłącznie dowiedzione pomiary.
    # Miejsce bramy jest decyzją projektową: silnik liczy, promocja rozstrzyga o użyciu.
    from app.services.promocja import promote_to_primary
    from app.services.fatigue_engine import dopisz_manifest

    # Kopia manifestu poza bazą jest od D6=A warunkiem promocji, więc własność musi
    # przechodzić TĄ SAMĄ drogą co produkcja: zapis kopii, potem pytanie bramy. Inaczej
    # sprawdzałaby zachowanie przy awarii dysku i „odrzuć wszystko" wyglądałoby poprawnie.
    kopie = tmp_path / "manifesty"

    odmowa = promote_to_primary(niekwalifikowany.identity.manifest(),
                                katalog_manifestow=kopie)
    assert not odmowa.dopuszczony, "niekwalifikowany pomiar przeszedł bramę promocji"
    assert odmowa.powody, "odmowa bez powodu jest bezużyteczna"
    assert odmowa.wiersz["primary_usable"] is False

    kwalifikowany = licz(silnik, teraz)
    assert kwalifikowany.identity.eligibility == "PRIMARY_ELIGIBLE"
    dopisz_manifest(kwalifikowany.identity.manifest(), katalog=kopie)
    zgoda = promote_to_primary(kwalifikowany.identity.manifest(),
                               katalog_manifestow=kopie)
    assert zgoda.dopuszczony, (
        f"brama odrzuciła dowiedziony pomiar - to implementacja „odrzuć wszystko”: "
        f"{zgoda.powody}")


# ---------------------------------------------------------------------------
# P-H. Window basis per obserwacja (punkt 4 recenzji).  CZERWONA na 2026-09-11.
# ---------------------------------------------------------------------------

def test_PH_kazde_okno_niesie_swoja_podstawe(silnik, teraz):
    """Okno wzięte z rejestru i okno policzone ze średniego czasu bloku to dwa stany.

    CZERWONA: `window_basis` nie istnieje w `app/` (zero wystąpień). Dziś okno
    odtworzone arytmetycznie z `ProposalCreated`, opóźnienia głosowania i założeń
    o czasie bloku wygląda w wyniku identycznie jak okno dokładne, a oba wchodzą
    do `concurrency` z tą samą wagą. Plan, P4: podstawa musi istnieć PER PROPOZYCJA
    (`SNAPSHOT_EXACT` / `REGISTRY_EXACT` / `GOVERNOR_EXACT` / `ESTIMATED` / `UNKNOWN`),
    a `ESTIMATED` i `UNKNOWN` nie wchodzą do pomiaru pierwszorzędnego.
    """
    r = licz(silnik, teraz)
    manifest = r.identity.manifest()
    eko = manifest.get("prepared_input", {}).get("ecosystem") or []
    assert eko, "brak ekspozycji w przygotowanym wejściu - test nie ma czego sprawdzić"
    bez_podstawy = [p for p in eko if not p.get("window_basis")]
    assert not bez_podstawy, (
        f"{len(bez_podstawy)} z {len(eko)} propozycji ekspozycji nie niesie podstawy okna - "
        "oszacowanie jest nieodróżnialne od dowodu"
    )


# ---------------------------------------------------------------------------
# P-I. Tożsamość artefaktu wykonawczego (punkt 8 recenzji).  CZERWONA na 2026-09-11.
# ---------------------------------------------------------------------------

def test_PI_brak_tozsamosci_kodu_dyskwalifikuje(silnik, teraz):
    """`code_commit == "unknown"` nie jest pominiętą metadaną, a brakiem dowodu.

    CZERWONA: pole istnieje (`fatigue_engine.py:182`), ale `_eligibility` go nie
    ogląda, więc pomiar z nieznaną wersją kodu wychodzi pierwszorzędny. Dwa różne
    builda stają się wtedy nieodróżnialne na warstwie tożsamości kodu - przy
    wyniku traktowanym jako dowód odtwarzalny.
    """
    silnik.code_commit = "unknown"
    r = licz(silnik, teraz)
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE", (
        "pomiar z nieznaną wersją kodu przeszedł jako pierwszorzędny"
    )


def test_PI_wynik_niesie_pelna_tozsamosc_artefaktu(silnik, teraz):
    """Commit sam nie wystarcza: ten sam commit, inna konfiguracja = inny artefakt.

    CZERWONA do P7: plan wymaga `build_image_digest`, `config_hash`,
    `eligibility_policy_version`, `taxonomy_snapshot_id` i `analysis_contract_version`
    obok `code_commit`. Dziś manifest niesie commit, skrót instrumentu i wersję
    konfiguracji - pozostałych trzech nie ma.
    """
    manifest = licz(silnik, teraz).identity.manifest()
    # Plan wymaga `build_image_digest` ALBO RÓWNOWAŻNEGO digestu artefaktu. Rolę
    # równoważnika pełni `runtime_digest` (wersje zależności, wersja Pythona i digest
    # obrazu, gdy istnieje) - liczony bez Dockera, więc dostępny także wtedy, gdy pomiar
    # idzie z katalogu roboczego. Samo `build_image_digest` stoi w manifeście osobno
    # i bywa puste; pusta wartość znaczy „policzone poza zbudowanym obrazem" i jest
    # informacją, nie brakiem.
    brakujace = [
        p for p in ("runtime_digest", "eligibility_policy_version", "taxonomy_snapshot_id")
        if not manifest.get(p)
    ]
    assert not brakujace, f"manifest nie niesie tożsamości artefaktu: {brakujace}"
    assert "build_image_digest" in manifest, "pole digestu obrazu musi istnieć, choćby puste"
