"""P10: wynik niekwalifikowany nie może awansować przez pominięcie pola.

Sekcja 11 planu domknięcia. Zmierzone 11.09 w trzech ogniwach: eksport zwracał
`fatigue_score` niezależnie od werdyktu i ostrzegał tylko na stderr, zbiór analityczny nie
miał kolumny werdyktu, a analiza filtrowała wyłącznie braki danych. Pomiar
`NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS` wchodził więc do korelacji H_val jako zwykła liczba.

To jedyne z dzisiejszych znalezisk dotyczące WYNIKU hipotezy głównej, nie higieny pomiaru.

Uruchomienie: python3 -m pytest tests/test_granica_promocji.py -v
"""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import (  # noqa: E402
    ERROR, HEALTHY_COMPLETE, FatigueEngine, SourceReceipt, dopisz_manifest,
)
from app.services.promocja import (  # noqa: E402
    ANALYSIS_CONTRACT_VERSION, POLA_WYMAGANE, promote_to_primary,
    sprawdz_zbior_analityczny,
)

T = 1_780_000_000
WYMAGANE = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")


def obs(id_, dni_temu, *, kategoria="grants"):
    t = T - dni_temu * 86_400
    return SimpleNamespace(
        id=id_, title=f"Proposal {id_}", body="tresc " * 60, state="closed",
        start=t - 86_400, end=t + 86_400, voted_at=t, cast_at=t,
        category=kategoria, source_domain="snapshot", source="snapshot",
        source_vote_id=f"v-{id_}", native_proposal_id=id_, voter="0xA",
        window_basis="SNAPSHOT_EXACT", window_uncertainty_reason="",
        lifecycle_id=id_, linked_stage_ids=[id_], link_basis="NATIVE_ID",
    )


def pokwitowania(taxonomy_state=HEALTHY_COMPLETE):
    return [SourceReceipt(
        z, taxonomy_state if z == "taxonomy" else HEALTHY_COMPLETE,
        events=3, page_count=1, record_count=3, limit_hit=False,
        taxonomy_snapshot_id="tax:testowy0000000@2026-09-11" if z == "taxonomy" else "")
        for z in WYMAGANE]


KATALOG_KOPII = None       # ustawiany przez fixture `kopie_manifestow`


@pytest.fixture(autouse=True)
def kopie_manifestow(tmp_path):
    """Katalog kopii manifestow per test (D6=A).

    Brama pyta o FAKT istnienia kopii, wiec test musi przejsc te sama droge co produkcja:
    zapis kopii, potem pytanie bramy. Bez tego kazdy test promocji sprawdzalby zachowanie
    przy awarii dysku, a nie przy poprawnym zapisie."""
    global KATALOG_KOPII
    KATALOG_KOPII = tmp_path / "manifesty"
    yield KATALOG_KOPII
    KATALOG_KOPII = None


def brama(manifest, wynik=None, *, z_kopia=True):
    """Wywolanie bramy po tej samej drodze co w `main.py`: najpierw kopia, potem pytanie.

    Pusty manifest przechodzi WPROST do bramy - `main.py` nie ma czego wtedy zapisac,
    a brama ma odpowiedziec odmowa, nie wyjatkiem."""
    if z_kopia and manifest:
        dopisz_manifest(manifest, katalog=KATALOG_KOPII)
    return promote_to_primary(manifest, wynik, katalog_manifestow=KATALOG_KOPII)


def zmierz(taxonomy_state=HEALTHY_COMPLETE):
    eng = FatigueEngine("fatigue_config.yaml")
    cel = obs("target", 0, kategoria="network changes")
    return eng.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel, obs("h1", 10)],
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=[obs("eco-1", 1)],
        source_receipts=pokwitowania(taxonomy_state))


# ---------------------------------------------------------------------------
# Brama przepuszcza dowiedzione, odrzuca resztę
# ---------------------------------------------------------------------------

def test_brama_i_silnik_zgadzaja_sie_co_do_ZAKRESU_skladnikow():
    """Pomiar, który silnik uznał za pierwszorzędny, ma przejść bramę. Bez wyjątków.

    POWÓD POWSTANIA - regresja zmierzona 11.09, nie hipoteza. Po wyjęciu `novelty`
    z DFI-core (D1=B) smoke na 40 delegatach z ramy 3121 dał **23 PRIMARY_ELIGIBLE
    i 0 przepuszczonych przez tę bramę**: silnik przestał dyskwalifikować za niepełną
    podstawę `novelty`, a brama trzymała własną, bezwarunkową kopię tej reguły.

    To jest *recursive semantic regression* z recenzji 78179 - naprawa na jednej warstwie,
    a warstwę niżej druga kopia reguły odtwarza stan sprzed naprawy. Ten warunek jest
    czerwoną linią między warstwami: rozjazd werdyktów ma wywalać test, nie cichnąć
    w statystyce smoke'u.

    Odtworzony jest kształt z terenu: kategoria celu nieznana u 37 z 40 zbadanych."""
    eng = FatigueEngine("fatigue_config.yaml")
    cel = obs("target", 0, kategoria="")          # jak u większości delegatów w polu
    wynik = eng.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel, obs("h1", 10)],
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=[obs("eco-1", 1)],
        source_receipts=pokwitowania())

    assert wynik.identity.eligibility == "PRIMARY_ELIGIBLE", wynik.identity.eligibility_reasons
    assert wynik.identity.novelty_basis not in ("COMPLETE", ""), (
        "test stracił moc: podstawa novelty jest pełna, więc nie sprawdza rozjazdu")

    p = brama(wynik.identity.manifest(), {"fatigue_score": wynik.fatigue_score})
    assert p.dopuszczony, (
        f"silnik: PRIMARY_ELIGIBLE, brama: odmowa - {p.powody}")
    assert p.wiersz["primary_components"], "zbiór analityczny nie niesie zakresu pomiaru"


def test_stary_manifest_bez_zakresu_nadal_podlega_zakazowi_novelty():
    """Manifest bez `primary_components` pochodzi sprzed D1=B, czyli z czasu, gdy `novelty`
    BYŁA składnikiem wyniku. Brama ma go wtedy odrzucić - fail-closed.

    Bez tego warunku naprawa rozjazdu zamieniłaby się w ciche wpuszczenie starych pomiarów
    liczonych inną regułą."""
    eng = FatigueEngine("fatigue_config.yaml")
    cel = obs("target", 0, kategoria="")
    wynik = eng.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel, obs("h1", 10)],
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=[obs("eco-1", 1)],
        source_receipts=pokwitowania())

    stary = dict(wynik.identity.manifest())
    stary.pop("primary_components", None)          # kształt manifestu sprzed 1.8.0
    p = brama(stary, {"fatigue_score": wynik.fatigue_score})

    assert not p.dopuszczony
    assert any("novelty" in x for x in p.powody), p.powody
    assert p.do_wrazliwosci, "odrzucony pomiar ma zostać materiałem analizy wrażliwości"


def test_pomiar_kwalifikowany_przechodzi_brame():
    """Pierwsze świadomie: brama bez tego testu byłaby implementacją „odrzuć wszystko"."""
    r = zmierz()
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons
    p = brama(r.identity.manifest(), {"fatigue_score": r.fatigue_score})
    assert p.dopuszczony, p.powody
    assert p.wiersz["primary_usable"] is True
    assert p.wiersz["analysis_contract_version"] == ANALYSIS_CONTRACT_VERSION
    assert p.wiersz["dfi"] == r.fatigue_score


def test_pomiar_niekwalifikowany_nie_przechodzi_i_niesie_powod():
    """Werdykt silnika obowiązuje u bramy - brama go nie przegłosowuje."""
    r = zmierz(taxonomy_state=ERROR)
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    p = brama(r.identity.manifest())
    assert not p.dopuszczony
    assert p.powody, "odmowa bez powodu jest bezużyteczna"
    assert p.do_wrazliwosci, "pomiar odrzucony z H_val nadal wchodzi do analizy wrażliwości"


@pytest.mark.parametrize("pole", POLA_WYMAGANE)
def test_usuniecie_pola_nie_podnosi_kwalifikacji(pole):
    """SABOTAŻ Z PLANU: usunięcie pola z jednej warstwy musi dać fail-closed.

    To dokładnie przeciek, który był w eksporcie: brak kolumny werdyktu znaczył „brak
    ograniczeń", więc niekwalifikowany pomiar wyglądał jak każdy inny.
    """
    manifest = zmierz().identity.manifest()
    manifest[pole] = ""
    p = brama(manifest)
    assert not p.dopuszczony, f"pomiar bez pola {pole} przeszedł bramę"
    assert any(pole in x for x in p.powody), p.powody


def test_brak_manifestu_to_odmowa_nie_wyjatek():
    """Brak danych o pochodzeniu nie może wywracać potoku - ma go zatrzymać."""
    p = brama(None)
    assert not p.dopuszczony
    assert p.powody


def test_brama_sprawdza_podstawy_skladnikow_jeszcze_raz():
    """Manifest ze starszej wersji instrumentu nie zna dzisiejszych reguł.

    Brama jest ostatnim miejscem przed analizą, więc podstawy składników sprawdza
    ponownie - nawet gdy werdykt w manifeście mówi `PRIMARY_ELIGIBLE`.

    ZMIANA OD 1.8.0 (D1=B): powtórne sprawdzenie `novelty` pyta najpierw o ZAKRES pomiaru.
    Do tej wersji zakaz był bezwarunkowy i to on powodował, że po wyjęciu składnika z
    DFI-core brama odrzucała 23 z 23 pomiarów, które silnik uznał za pierwszorzędne.
    Zakaz obowiązuje tam, gdzie `novelty` faktycznie buduje wynik - a więc dla manifestów
    sprzed decyzji (bez pola) i dla instrumentu z przywróconym składnikiem.

    Warunek o oknach ekspozycji zostaje bez zmian: te wchodzą do `concurrency`, czyli do
    składnika pierwszorzędnego."""
    # novelty: zakaz pyta o zakres
    manifest = zmierz().identity.manifest()
    manifest["novelty_basis"] = "HISTORY_COVERAGE_INCOMPLETE"
    manifest["primary_components"] = ["volume", "concurrency", "burstiness",
                                      "reading_time", "novelty"]
    p = brama(manifest)
    assert not p.dopuszczony
    assert any("novelty" in x for x in p.powody)

    poza_zakresem = zmierz().identity.manifest()
    poza_zakresem["novelty_basis"] = "HISTORY_COVERAGE_INCOMPLETE"
    assert "novelty" not in poza_zakresem["primary_components"]
    assert brama(poza_zakresem).dopuszczony, (
        "składnik spoza zakresu nie ma prawa odbierać promocji pomiarowi")

    # okna ekspozycji: zakaz bezwarunkowy, bo niosą `concurrency`
    manifest2 = zmierz().identity.manifest()
    manifest2["prepared_input"]["ecosystem"][0]["window_basis"] = "ESTIMATED"
    p2 = brama(manifest2)
    assert not p2.dopuszczony
    assert any("window" in x for x in p2.powody)


# ---------------------------------------------------------------------------
# Zbiór analityczny: analiza ODMAWIA pracy na zbiorze bez kwalifikacji
# ---------------------------------------------------------------------------

def test_zbior_bez_kolumny_kwalifikacji_jest_odrzucany():
    """Brak kolumny to nie „zbiór bez ograniczeń", a zbiór o nieznanej zawartości."""
    brakujace = sprawdz_zbior_analityczny(["respondent_id", "dfi", "tlx_mental"])
    assert "primary_usable" in brakujace
    assert "eligibility" in brakujace


def test_zbior_kompletny_przechodzi():
    kolumny = ["respondent_id", "dfi", "primary_usable", "eligibility",
               "measurement_id", "analysis_contract_version"]
    assert sprawdz_zbior_analityczny(kolumny) == []


def test_wiersz_bramy_niesie_wszystko_co_analiza_musi_wiedziec():
    """Jedno miejsce buduje wiersz eksportu, więc kolumny nie mogą się rozejść z bramą."""
    p = brama(zmierz().identity.manifest())
    for pole in ("measurement_id", "eligibility", "instrument_version",
                 "eligibility_policy_version", "novelty_basis", "taxonomy_snapshot_id",
                 "runtime_digest", "code_commit", "analysis_contract_version",
                 "primary_usable"):
        assert pole in p.wiersz, f"wiersz eksportu bez {pole}"


# ---------------------------------------------------------------------------
# D6=A: kopia manifestu poza bazą jest warunkiem wejścia do H_val
# ---------------------------------------------------------------------------

def test_brak_kopii_manifestu_odbiera_promocje():
    """Pomiar bez kopii poza bazą nie jest odtwarzalny po jej utracie.

    Do 11.09 nieudany zapis kopii nie miał ŻADNEGO skutku: `dopisz_manifest` zwracało
    `False`, a `main.py` ignorowało wynik. Dokumentacja mówiła, że manifest jest dowodem
    mocniejszym niż baza - i jednocześnie jego brak niczego nie zmieniał."""
    r = zmierz()
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons

    p = brama(r.identity.manifest(), z_kopia=False)
    assert not p.dopuszczony
    assert any("kopii manifestu" in x for x in p.powody), p.powody
    assert p.do_wrazliwosci, "pomiar bez kopii nadal jest materiałem analizy wrażliwości"


def test_kopia_skasowana_po_rejestracji_daje_ten_sam_werdykt_co_niezapisana():
    """Brama pyta o FAKT, nie o flagę z chwili zapisu.

    Flaga opisywałaby to, co wydarzyło się przy rejestracji. Pytanie brzmi inaczej:
    czy ten pomiar da się dziś odtworzyć po utracie bazy."""
    r = zmierz()
    assert brama(r.identity.manifest()).dopuszczony

    for plik in KATALOG_KOPII.glob("pomiary-*.jsonl"):
        plik.unlink()

    po_skasowaniu = promote_to_primary(r.identity.manifest(),
                                       katalog_manifestow=KATALOG_KOPII)
    assert not po_skasowaniu.dopuszczony
    assert any("kopii manifestu" in x for x in po_skasowaniu.powody)


def test_POWTORNY_pomiar_nie_traci_promocji_przez_idempotencje():
    """NAJWAŻNIEJSZY warunek tej zmiany.

    `dopisz_manifest` zwracało `False` w DWÓCH stanach: przy awarii zapisu ORAZ gdy
    manifest już tam był, czyli przy sukcesie idempotencji. Oparcie kwalifikacji wprost
    na tej wartości odebrałoby promocję KAŻDEMU powtórnemu pomiarowi - a rejestracja jest
    idempotentna z założenia, więc drugie wywołanie tego samego pomiaru jest normą,
    nie wyjątkiem. Stąd trzy stany zamiast `bool`."""
    from app.services.fatigue_engine import (
        MANIFEST_JUZ_BYL, MANIFEST_ZAPISANY, dopisz_manifest as zapisz,
    )
    r = zmierz()
    manifest = r.identity.manifest()

    assert zapisz(manifest, katalog=KATALOG_KOPII) == MANIFEST_ZAPISANY
    assert zapisz(manifest, katalog=KATALOG_KOPII) == MANIFEST_JUZ_BYL, (
        "drugi zapis tego samego pomiaru ma być rozpoznany jako idempotencja")

    p = promote_to_primary(manifest, katalog_manifestow=KATALOG_KOPII)
    assert p.dopuszczony, (
        f"powtórny pomiar stracił promocję przez idempotencję zapisu: {p.powody}")
