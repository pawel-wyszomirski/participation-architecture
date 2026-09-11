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


def test_stan_TARGET_UNKNOWN_nie_daje_wartosci_pierwszorzednej(silnik):
    """Kategoria celu nieznana: dawniej 0,0 przez słowa kluczowe, czyli „rutynowa".

    To jest ten sam błąd, który zmierzyłam 11.09: liczba istniała, opisywała niewiedzę,
    a werdykt jej nie odróżniał.
    """
    cel = obs("target", 0, kategoria="")
    historia = [cel, obs("h1", 10, kategoria="grants")]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_TARGET_UNKNOWN
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert any("novelty" in x.lower() for x in r.identity.eligibility_reasons), (
        f"powód ma nazywać składnik: {r.identity.eligibility_reasons}")


def test_stan_HISTORY_INCOMPLETE_nie_daje_wartosci_pierwszorzednej(silnik):
    """Iloraz z podzbioru nie jest estymatą punktową.

    Przy pokryciu 1,2% - zmierzonym u uczestnika Fazy A - liczba „udział kategorii wśród
    wcześniejszych decyzji" opisuje jeden procent decyzji i milczy o dziewięćdziesięciu
    dziewięciu. Plan, 7.4: albo uzupełnić snapshot taksonomii, albo NOT_ELIGIBLE.
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
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"


@pytest.mark.parametrize("pokrycie_procent,sklasyfikowane,razem", [
    ("1,2%", 1, 83), ("1,8%", 1, 55), ("30,8%", 4, 13)])
def test_odbior_znane_pokrycia_uczestnikow_nie_daja_primary(
        silnik, pokrycie_procent, sklasyfikowane, razem):
    """Sekcja 7.5 planu: pokrycia 1,2%, 1,8% i 30,8% NIE MOGĄ wyjść jako novelty primary.

    Trzy liczby zmierzone u trójki uczestników Fazy A. Test odtwarza ich kształt:
    historia częściowo sklasyfikowana, reszta bez kategorii.
    """
    cel = obs("target", 0, kategoria="network changes")
    historia = [cel]
    historia += [obs(f"k{i}", 5 + i, kategoria="grants") for i in range(sklasyfikowane)]
    historia += [obs(f"n{i}", 50 + i, kategoria="") for i in range(razem - sklasyfikowane)]
    r = licz(silnik, cel, historia)

    assert r.identity.novelty_basis == NOVELTY_HISTORY_INCOMPLETE, pokrycie_procent
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE", (
        f"pokrycie {pokrycie_procent} dało pomiar pierwszorzędny")


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

def test_slowa_kluczowe_nie_sa_novelty_pierwszorzedna(silnik):
    """Dopasowanie po słowach to INNY konstrukt - cecha tekstu, nie stan czytającego.

    Wolno go policzyć do analizy wrażliwości; nie wolno go promować jako `novelty`.
    """
    cel = obs("target", 0, kategoria="",
              tytul="Emergency security council exploit response")
    r = licz(silnik, cel, [cel, obs("h1", 10, kategoria="grants")])

    assert r.identity.novelty_basis != NOVELTY_COMPLETE
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
