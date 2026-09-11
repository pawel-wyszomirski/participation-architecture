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
    ERROR, HEALTHY_COMPLETE, FatigueEngine, SourceReceipt,
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

def test_pomiar_kwalifikowany_przechodzi_brame():
    """Pierwsze świadomie: brama bez tego testu byłaby implementacją „odrzuć wszystko"."""
    r = zmierz()
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons
    p = promote_to_primary(r.identity.manifest(), {"fatigue_score": r.fatigue_score})
    assert p.dopuszczony, p.powody
    assert p.wiersz["primary_usable"] is True
    assert p.wiersz["analysis_contract_version"] == ANALYSIS_CONTRACT_VERSION
    assert p.wiersz["dfi"] == r.fatigue_score


def test_pomiar_niekwalifikowany_nie_przechodzi_i_niesie_powod():
    """Werdykt silnika obowiązuje u bramy - brama go nie przegłosowuje."""
    r = zmierz(taxonomy_state=ERROR)
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    p = promote_to_primary(r.identity.manifest())
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
    p = promote_to_primary(manifest)
    assert not p.dopuszczony, f"pomiar bez pola {pole} przeszedł bramę"
    assert any(pole in x for x in p.powody), p.powody


def test_brak_manifestu_to_odmowa_nie_wyjatek():
    """Brak danych o pochodzeniu nie może wywracać potoku - ma go zatrzymać."""
    p = promote_to_primary(None)
    assert not p.dopuszczony
    assert p.powody


def test_brama_sprawdza_podstawy_skladnikow_jeszcze_raz():
    """Manifest ze starszej wersji instrumentu nie zna dzisiejszych reguł.

    Brama jest ostatnim miejscem przed analizą, więc podstawy `novelty` i okien sprawdza
    ponownie - nawet gdy werdykt w manifeście mówi `PRIMARY_ELIGIBLE`.
    """
    manifest = zmierz().identity.manifest()
    manifest["novelty_basis"] = "HISTORY_COVERAGE_INCOMPLETE"
    p = promote_to_primary(manifest)
    assert not p.dopuszczony
    assert any("novelty" in x for x in p.powody)

    manifest2 = zmierz().identity.manifest()
    manifest2["prepared_input"]["ecosystem"][0]["window_basis"] = "ESTIMATED"
    p2 = promote_to_primary(manifest2)
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
    p = promote_to_primary(zmierz().identity.manifest())
    for pole in ("measurement_id", "eligibility", "instrument_version",
                 "eligibility_policy_version", "novelty_basis", "taxonomy_snapshot_id",
                 "runtime_digest", "code_commit", "analysis_contract_version",
                 "primary_usable"):
        assert pole in p.wiersz, f"wiersz eksportu bez {pole}"
