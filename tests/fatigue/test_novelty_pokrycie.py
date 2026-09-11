"""P6: `novelty` przestaje zamieniać niewiedzę w liczbę.

Punkt 6 recenzji 78179 i sekcja 7 planu domknięcia. Zmierzone 11.09 na kodzie: przy
nieznanej kategorii `_novelty_per_event` schodzi na dopasowanie po słowach kluczowych
i zwraca **0,0**, czyli „decyzja rutynowa". Jedna liczba opisuje dwa różne stany świata:
*ten delegat robi to stale* oraz *nie wiemy nic o kategoriach*. Docstring tej samej
funkcji zabrania dokładnie tego, co kod robi.

Pokrycie taksonomią u trójki uczestników Fazy A: 1,2% / 1,8% / 30,8%. Zejście na słowa
kluczowe jest więc stanem normalnym, nie wyjątkiem - a `novelty` przy wadze 5% wnosi
-0,1% wariancji DFI, czyli składnik nie niesie informacji i jednocześnie udaje, że niesie.

Kontrakt z sekcji 7.3 planu - cztery ROZŁĄCZNE stany:

    NO_PRIOR_OBSERVED_DECISIONS_IN_COMPLETE_CORPUS  brak wcześniejszych decyzji przy
                                                     DOWIEDZIONEJ kompletności -> 1,0
    TARGET_CATEGORY_UNKNOWN                          kategoria celu nieznana -> brak primary
    HISTORY_COVERAGE_INCOMPLETE                      historia bez pełnej klasyfikacji ->
                                                     brak POJEDYNCZEJ wartości primary
    COMPLETE                                         pełny mianownik -> wartość

Stan pierwszy NIE nazywa się „pierwszy głos człowieka": to brak wcześniejszych
ZAOBSERWOWANYCH decyzji adresu w kompletnym, zdefiniowanym korpusie.

Uruchomienie: python3 -m pytest tests/fatigue/test_novelty_pokrycie.py -v
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import (  # noqa: E402
    HEALTHY_COMPLETE, NOVELTY_COMPLETE, NOVELTY_HISTORY_INCOMPLETE, NOVELTY_NO_PRIOR,
    NOVELTY_TARGET_UNKNOWN, FatigueEngine, SourceReceipt,
)

T = 1_780_000_000
WYMAGANE = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")


def obs(id_, dni_temu, *, kategoria="grants", tytul=None, body="tresc " * 60):
    t = T - dni_temu * 86_400
    return SimpleNamespace(
        id=id_, title=tytul or f"Proposal {id_}", body=body, state="closed",
        start=t - 86_400, end=t + 86_400, voted_at=t, cast_at=t,
        category=kategoria, source_domain="snapshot", source="snapshot",
        source_vote_id=f"v-{id_}", native_proposal_id=id_, voter="0xA",
        window_basis="SNAPSHOT_EXACT", window_uncertainty_reason="",
        lifecycle_id=id_, linked_stage_ids=[id_], link_basis="NATIVE_ID",
    )


def pokwitowania(taxonomy_snapshot_id="tax:abc123@2026-09-11"):
    out = []
    for z in WYMAGANE:
        kw = {"events": 3, "page_count": 1, "record_count": 3, "limit_hit": False}
        if z == "taxonomy":
            kw["taxonomy_snapshot_id"] = taxonomy_snapshot_id
        out.append(SourceReceipt(z, HEALTHY_COMPLETE, **kw))
    return out


@pytest.fixture
def silnik():
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710})
    return eng


@pytest.fixture
def silnik_novelty_pierwszorzedna():
    """Instrument z `novelty` PRZYWRÓCONĄ do składników pierwszorzędnych.

    Od 1.8.0 (D1=B) podstawa `novelty` nie dyskwalifikuje pomiaru, bo składnik nie
    wchodzi do DFI-core. Ta konfiguracja sprawdza, że bramka nie została SKASOWANA,
    tylko uwarunkowana zakresem: gdy ktoś kiedyś przywróci składnik do H_val,
    dyskwalifikacja wraca tym samym ruchem."""
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710})
    eng.config["primary_components_per_event"] = [
        "volume", "concurrency", "burstiness", "reading_time", "novelty"]
    return eng


def powod_novelty(wynik):
    return [x for x in wynik.identity.eligibility_reasons if "novelty" in x.lower()]


def notatka_novelty(wynik):
    return [x for x in wynik.identity.eligibility_notes if "novelty" in x.lower()]


def licz(silnik, cel, historia, **kw):
    return silnik.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=historia,
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=kw.pop("ekspozycja", [obs("eco-1", 1)]),
        source_receipts=kw.pop("receipts", pokwitowania()), **kw)


# ---------------------------------------------------------------------------
# Cztery stany
# ---------------------------------------------------------------------------

def test_stan_COMPLETE_daje_wartosc(silnik):
    """Pełny mianownik: wszystkie wcześniejsze decyzje sklasyfikowane."""
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10, kategoria="grants"), obs("h2", 20, kategoria="grants")]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_COMPLETE
    assert r.components.novelty == 1.0, "kategoria nowa dla tego delegata"
    assert r.identity.category_coverage["coverage_ratio"] == 1.0
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons


def test_stan_NO_PRIOR_to_wiedza_nie_brak(silnik):
    """Brak wcześniejszych decyzji w KOMPLETNYM korpusie daje 1,0 - i to jest pomiar.

    Nazwa stanu mówi dokładnie tyle, ile wiemy: żadnej wcześniejszej ZAOBSERWOWANEJ
    decyzji tego adresu. Nie „pierwszy głos człowieka" - osoba może mieć historię
    pod innym adresem albo w innym DAO.
    """
    cel = obs("target", 0, kategoria="network changes")
    r = licz(silnik, cel, [cel])

    assert r.identity.novelty_basis == NOVELTY_NO_PRIOR
    assert r.components.novelty == 1.0
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons


def test_stan_TARGET_UNKNOWN_jest_NAZWANY_i_nie_wchodzi_do_core(silnik):
    """Kategoria celu nieznana: dawniej 0,0 przez słowa kluczowe, czyli „rutynowa".

    To jest ten sam błąd, który zmierzyłam 11.09: liczba istniała, opisywała niewiedzę,
    a werdykt jej nie odróżniał.

    Od 1.8.0 (D1=B) skutek jest inny niż w P6, a zakaz ten sam: stan ma być NAZWANY,
    a liczba nie ma prawa wejść do pomiaru konfirmacyjnego. P6 osiągał to dyskwalifikacją
    całego pomiaru, bo `novelty` była wtedy składnikiem H_val. Teraz nie jest, więc
    jej podstawa jest notatką - a wykluczenie z wyniku robi zakres składników.
    """
    cel = obs("target", 0, kategoria="")
    historia = [cel, obs("h1", 10, kategoria="grants")]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_TARGET_UNKNOWN
    assert "novelty" not in r.identity.primary_components, (
        "novelty wróciła do składników pierwszorzędnych - zmiana zakresu bez decyzji")
    assert notatka_novelty(r), (
        f"stan ma być nazwany w notatkach: {r.identity.eligibility_notes}")
    assert not powod_novelty(r), (
        f"novelty nie ma dyskwalifikować pomiaru, który jej nie używa: "
        f"{r.identity.eligibility_reasons}")


def test_TARGET_UNKNOWN_nadal_dyskwalifikuje_gdy_novelty_jest_pierwszorzedna(
        silnik_novelty_pierwszorzedna):
    """BEZPIECZNIK, nie powtórka: bramka P6 ma wrócić razem ze składnikiem.

    Gdyby warunek został skasowany zamiast uwarunkowany zakresem, przywrócenie `novelty`
    do H_val cicho wpuściłoby do analizy konfirmacyjnej wartości policzone na nieznanej
    kategorii - czyli dokładnie stan sprzed P6."""
    cel = obs("target", 0, kategoria="")
    r = licz(silnik_novelty_pierwszorzedna, cel, [cel, obs("h1", 10, kategoria="grants")])

    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert powod_novelty(r), f"powód ma nazywać składnik: {r.identity.eligibility_reasons}"


def test_stan_HISTORY_INCOMPLETE_jest_ZMIERZONY_i_nie_wchodzi_do_core(silnik):
    """Iloraz z podzbioru nie jest estymatą punktową.

    Przy pokryciu 1,2% - zmierzonym u uczestnika Fazy A - liczba „udział kategorii wśród
    wcześniejszych decyzji" opisuje jeden procent decyzji i milczy o dziewięćdziesięciu
    dziewięciu. Pokrycie ma być policzone i zapisane niezależnie od tego, że składnik
    wypadł z DFI-core: analiza wrażliwości potrzebuje wiedzieć, na czym stała.
    """
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10, kategoria="grants"), obs("h2", 20, kategoria=""),
                obs("h3", 30, kategoria="")]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_HISTORY_INCOMPLETE
    pokrycie = r.identity.category_coverage
    assert pokrycie["classified_count"] == 1
    assert pokrycie["eligible_history_count"] == 3
    assert 0 < pokrycie["coverage_ratio"] < 1
    assert notatka_novelty(r), r.identity.eligibility_notes
    assert not powod_novelty(r), r.identity.eligibility_reasons


@pytest.mark.parametrize("pokrycie_procent,sklasyfikowane,razem", [
    ("1,2%", 1, 83), ("1,8%", 1, 55), ("30,8%", 4, 13)])
def test_odbior_znane_pokrycia_uczestnikow_nie_blokuja_juz_pomiaru(
        silnik, pokrycie_procent, sklasyfikowane, razem):
    """Trzy pokrycia zmierzone u trójki uczestników Fazy A: 1,2%, 1,8%, 30,8%.

    Do 1.7.0 każde z nich dawało `NOT_ELIGIBLE`, i to jest powód, dla którego pomiar
    wykonalności próby (P12, D38) zwrócił 0 z 15 kwalifikowalnych. Po D1=B mają
    przechodzić - z podstawą `novelty` zapisaną w notatce, nie w dyskwalifikacji.

    Odbiór D1: warunek sprawdza to, co decyzja miała zmienić.
    """
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel]
    historia += [obs(f"k{i}", 5 + i, kategoria="grants") for i in range(sklasyfikowane)]
    historia += [obs(f"n{i}", 50 + i, kategoria="") for i in range(razem - sklasyfikowane)]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_HISTORY_INCOMPLETE, pokrycie_procent
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", (
        f"pokrycie {pokrycie_procent}: {r.identity.eligibility_reasons}")
    assert notatka_novelty(r), pokrycie_procent


# ---------------------------------------------------------------------------
# Pokrycie liczone na FAKTYCZNYM mianowniku (sekcja 7.2)
# ---------------------------------------------------------------------------

def test_pokrycie_liczone_na_tym_samym_korpusie_co_novelty(silnik):
    """Mianownik pokrycia to historia, z której `novelty` bierze mianownik.

    Liczenie pokrycia na innym zbiorze - na przykład na całym rejestrze taksonomii -
    dałoby procent bez związku z tym pomiarem. Własny cykl celu jest wyłączony z historii,
    więc nie może wejść do mianownika pokrycia.
    """
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10, kategoria="grants"), obs("h2", 20, kategoria="grants")]
    r = licz(silnik, cel, historia)

    p = r.identity.category_coverage
    assert p["eligible_history_count"] == 2, "cel nie wchodzi do swojego mianownika"
    assert p["classified_count"] == 2
    assert p["coverage_basis"], "pokrycie ma nazywać, na czym stoi"


def test_brakujace_identyfikatory_sa_wymienione(silnik):
    """Lista nieklasyfikowanych decyzji - żeby dało się je uzupełnić, nie tylko policzyć."""
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10, kategoria="grants"), obs("bez-kategorii", 20, kategoria="")]
    r = licz(silnik, cel, historia)

    brakujace = r.identity.category_coverage.get("missing_ids") or []
    assert "bez-kategorii" in brakujace


# ---------------------------------------------------------------------------
# Zamrożony snapshot taksonomii (sekcja 7.1)
# ---------------------------------------------------------------------------

def test_pomiar_niesie_identyfikator_snapshotu_taksonomii(silnik):
    """Bez identyfikatora snapshotu nie da się powiedzieć, JAKI zbiór kategorii mierzył.

    Rejestr żyje: kategoria dopisana po pomiarze zmieniłaby historyczny wynik przy
    ponownym liczeniu, a pomiar nie miałby jak tego pokazać.
    """
    cel = obs("target", 0, kategoria="network changes")
    r = licz(silnik, cel, [cel, obs("h1", 10, kategoria="grants")])

    assert r.identity.taxonomy_snapshot_id == "tax:abc123@2026-09-11"
    assert r.identity.manifest().get("taxonomy_snapshot_id")


def test_brak_identyfikatora_snapshotu_dyskwalifikuje(silnik):
    """Taksonomia bez identyfikatora snapshotu nie jest zamrożonym źródłem."""
    cel = obs("target", 0, kategoria="network changes")
    r = licz(silnik, cel, [cel, obs("h1", 10, kategoria="grants")],
             receipts=pokwitowania(taxonomy_snapshot_id=""))

    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert any("snapshot" in x.lower() for x in r.identity.eligibility_reasons), (
        r.identity.eligibility_reasons)


# ---------------------------------------------------------------------------
# Zejście na słowa kluczowe nigdy nie jest pomiarem pierwszorzędnym
# ---------------------------------------------------------------------------

def test_slowa_kluczowe_nie_sa_novelty_pierwszorzedna(silnik, silnik_novelty_pierwszorzedna):
    """Dopasowanie po słowach to INNY konstrukt - cecha tekstu, nie stan czytającego.

    Wolno go policzyć do analizy wrażliwości; nie wolno go promować jako `novelty`.
    Zakaz promocji trzyma się dwiema drogami naraz: przy obecnym zakresie liczba nie
    wchodzi do DFI-core, a gdyby zakres wrócił - dyskwalifikuje pomiar.
    """
    cel = obs("target", 0, kategoria="",
              tytul="Emergency security council exploit response")
    r = licz(silnik, cel, [cel, obs("h1", 10, kategoria="grants")])

    assert r.identity.novelty_basis != NOVELTY_COMPLETE
    assert "novelty" not in r.identity.primary_components
    assert notatka_novelty(r), r.identity.eligibility_notes

    wrocone = licz(silnik_novelty_pierwszorzedna, cel,
                   [cel, obs("h1", 10, kategoria="grants")])
    assert wrocone.identity.eligibility != "PRIMARY_ELIGIBLE"


# ---------------------------------------------------------------------------
# D1=B: zakres pomiaru pierwszorzędnego (11.09)
# ---------------------------------------------------------------------------

def test_kategorie_nie_ruszaja_DFI_core_ale_ruszaja_wrazliwosc(silnik):
    """Własność, nie przypadek: dwie historie różniące się WYŁĄCZNIE kategoriami mają
    dać identyczny DFI-core i różny `sensitivity_score`.

    Gdyby kategoria wpływała na wynik pierwszorzędny, decyzja D1 byłaby wpisana tylko
    w konfigurację, a nie w liczbę - i pomiar 0 z 15 wróciłby przy pierwszym pomiarze
    z niepełną taksonomią."""
    cel = obs("target", 0, kategoria="network changes")
    wspolna = [cel, obs("h1", 10), obs("h2", 20)]

    a = licz(silnik, cel, [cel, obs("h1", 10, kategoria="grants"),
                           obs("h2", 20, kategoria="grants")])
    b = licz(silnik, cel, [cel, obs("h1", 10, kategoria="network changes"),
                           obs("h2", 20, kategoria="network changes")])

    assert len(wspolna) == 3
    assert a.fatigue_score == b.fatigue_score, (
        "kategoria przesunęła DFI-core - `novelty` wciąż wpływa na pomiar pierwszorzędny")
    assert a.components.novelty != b.components.novelty, "test stracił moc: novelty równe"
    assert a.identity.sensitivity_score != b.identity.sensitivity_score, (
        "analiza wrażliwości przestała widzieć kategorie - została bez wejścia")


def test_skala_DFI_core_siega_stu(silnik):
    """Dzielnik 0,95 przywraca skalę: komplet składników pierwszorzędnych przy suficie
    ma dać 100,0, a nie 95,0.

    Bez dzielnika maksimum DFI-core wynosiłoby 95 i cała góra skali - w tym pasmo
    CRITICAL - byłaby nieosiągalna dla każdego delegata."""
    from app.services.fatigue_engine import FatigueComponents

    sufit = FatigueComponents(volume=1.0, concurrency=1.0, burstiness=1.0,
                              reading_time=1.0, novelty=0.0)
    wynik = silnik._aggregate_score(
        sufit, silnik.config["weights"],
        silnik.config["primary_components_per_event"])

    assert wynik == 100.0, wynik


def test_progi_per_event_sa_ODDZIELNE_od_progow_ekosystemowych(silnik):
    """Wariant per-event ma czytać `thresholds_per_event`, nie `thresholds`.

    Powód powstania: sabotaż z 11.09 podmienił sekcję progów na ekosystemową i CAŁA
    suita (334 testy) przeszła. Skala DFI-core jest inna - dzieli przez 0,95 - więc
    ciche zejście na progi wariantu grantowego przesuwałoby ludzi między pasmami przy
    niezmienionym obciążeniu i nic by tego nie pokazało.

    Pasmo bierze się z progu, a pasmo jest tym, co widzi uczestnik na panelu."""
    t_eko = silnik.config["thresholds"]
    t_pe = silnik.config["thresholds_per_event"]
    assert t_pe["low"] != t_eko["low"], (
        "test straciłby moc przy identycznych progach - rozróżnienie musi być widoczne")

    # Wartość w szczelinie między progami: LOW na skali per-event, MODERATE na starej.
    posrednia = (t_eko["low"] + t_pe["low"]) / 2
    assert silnik._determine_status(posrednia, "thresholds_per_event") == "LOW"
    assert silnik._determine_status(posrednia) == "MODERATE"

    # I to samo na PEŁNEJ ścieżce pomiaru, nie tylko na funkcji progów: podmiana progów
    # per-event ma zmienić status wyniku. Gdyby silnik czytał sekcję ekosystemową,
    # ta podmiana nie miałaby żadnego skutku - dokładnie tak wyglądał sabotaż.
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10), obs("h2", 20)]
    przed = licz(silnik, cel, historia)
    silnik.config["thresholds_per_event"] = {"low": 0.1, "moderate": 0.2, "high": 0.3}
    po = licz(silnik, cel, historia)

    assert przed.status != po.status, (
        f"progi per-event nie mają wpływu na status ({przed.status}) - silnik czyta "
        "inną sekcję konfiguracji")
    assert po.status == "CRITICAL"


def test_kolejnosc_skladnikow_w_konfiguracji_nie_zmienia_WYNIKU(silnik):
    """Permutacja listy zakresu nie ma prawa ruszyć LICZBY.

    Suma zmiennoprzecinkowa zależy od kolejności składników, a lista w YAML-u jest
    pisana ręcznie. Ta sama klasa błędu co permutacja historii z 10.09 - stąd
    kanonizacja kolejności w silniku.

    TOŻSAMOŚĆ natomiast zmienić się MOŻE i tego tu nie sprawdzamy. Pierwsza wersja
    tego warunku żądała niezmiennego `measurement_id` i była sprzeczna z kontraktem
    instrumentu: `instrument_hash` to skrót BAJTÓW pliku konfiguracji, więc każda
    edycja - również przestawienie nazw w liście czy dopisanie komentarza - daje nową
    tożsamość świadomie (`_load_config`). Manifest ma mówić, który plik obowiązywał,
    nie które wartości z niego wynikły. Wymaganie stałego identyfikatora przy zmienionym
    pliku znosiłoby tamtą zasadę bez decyzji."""
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel, obs("h1", 10), obs("h2", 20)]

    a = licz(silnik, cel, historia)
    silnik.config["primary_components_per_event"] = [
        "reading_time", "burstiness", "volume", "concurrency"]
    b = licz(silnik, cel, historia)

    assert a.fatigue_score == b.fatigue_score, (
        "kolejność składników w konfiguracji przesunęła wynik pomiaru")
    assert a.identity.primary_components == b.identity.primary_components, (
        "zakres zapisany w manifeście zależy od kolejności w pliku - brak kanonizacji")
