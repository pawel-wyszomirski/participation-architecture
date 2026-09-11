"""P7: tożsamość kodu to tożsamość ARTEFAKTU WYKONAWCZEGO, nie sam commit.

Punkt 8 recenzji 78179 i sekcja 8 planu domknięcia. Dwie rzeczy naraz:

1. `code_commit == "unknown"` przechodził jako pomiar pierwszorzędny. Pole istniało
   (`fatigue_engine.py:182`), a `_eligibility` go nie oglądało. Brak tożsamości kodu nie
   jest pominiętą metadaną, gdy wynik traktuje się jako dowód odtwarzalny.
2. Sam commit nie wystarcza. Dwa uruchomienia z tego samego commitu mogą różnić się
   konfiguracją albo wersją zależności - i wtedy są nieodróżnialne na warstwie tożsamości,
   choć mogą liczyć inaczej.

Kontrakt: pomiar niesie `code_commit`, skrót konfiguracji, wersję polityki kwalifikacji,
skrót środowiska wykonawczego, wersję schematu tożsamości i identyfikator snapshotu
taksonomii. Brak któregokolwiek wymaganego elementu dyskwalifikuje.

Uruchomienie: python3 -m pytest tests/fatigue/test_tozsamosc_artefaktu.py -v
"""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import (  # noqa: E402
    HEALTHY_COMPLETE, FatigueEngine, SourceReceipt,
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


def pokwitowania():
    return [SourceReceipt(
        z, HEALTHY_COMPLETE, events=3, page_count=1, record_count=3, limit_hit=False,
        taxonomy_snapshot_id="tax:testowy0000000@2026-09-11" if z == "taxonomy" else "")
        for z in WYMAGANE]


@pytest.fixture
def silnik():
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710})
    return eng


def licz(silnik):
    cel = obs("target", 0, kategoria="network changes")
    return silnik.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel, obs("h1", 10)],
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=[obs("eco-1", 1)], source_receipts=pokwitowania())


# ---------------------------------------------------------------------------
# Brak tożsamości kodu dyskwalifikuje
# ---------------------------------------------------------------------------

def test_nieznany_commit_dyskwalifikuje(silnik):
    """`unknown` to brak dowodu, nie drobiazg opisowy."""
    silnik.code_commit = "unknown"
    r = licz(silnik)
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert any("code" in x.lower() for x in r.identity.eligibility_reasons), (
        r.identity.eligibility_reasons)


def test_pusty_commit_dyskwalifikuje_tak_samo(silnik):
    """Pusty łańcuch i `unknown` znaczą to samo - i muszą kończyć się tak samo."""
    silnik.code_commit = ""
    r = licz(silnik)
    assert r.identity.eligibility != "PRIMARY_ELIGIBLE"


def test_znany_commit_przechodzi(silnik):
    """Odwrotna strona bramki: prawdziwy commit nie blokuje pomiaru."""
    r = licz(silnik)
    assert r.identity.code_commit not in ("", "unknown")
    assert r.identity.eligibility == "PRIMARY_ELIGIBLE", r.identity.eligibility_reasons


# ---------------------------------------------------------------------------
# Komplet tożsamości artefaktu w manifeście
# ---------------------------------------------------------------------------

def test_manifest_niesie_komplet_tozsamosci_artefaktu(silnik):
    """Sześć elementów, każdy odpowiada na inne pytanie o powstanie liczby."""
    m = licz(silnik).identity.manifest()
    for pole in ("code_commit", "instrument_hash", "instrument_version",
                 "identity_schema_version", "eligibility_policy_version",
                 "runtime_digest", "taxonomy_snapshot_id"):
        assert m.get(pole), f"manifest bez {pole}"


def test_wersja_polityki_kwalifikacji_zmienia_sie_z_regulami(silnik):
    """Polityka kwalifikacji jest częścią instrumentu, więc ma własną wersję.

    Liczona ze SKRÓTU reguł, nie wpisywana ręcznie - ręcznej nie da się zapomnieć podbić
    tylko wtedy, gdy nikt nie zmienia reguł.
    """
    przed = licz(silnik).identity.eligibility_policy_version
    assert przed

    silnik.config["eligibility"] = dict(silnik.config["eligibility"])
    silnik.config["eligibility"]["eligible_coverage"] = ["COMPLETE"]
    po = licz(silnik).identity.eligibility_policy_version
    assert po != przed, "zmiana reguł kwalifikacji nie ruszyła wersji polityki"


def test_slad_wykonawczy_rozroznia_inne_zaleznosci(silnik, monkeypatch):
    """Odbiór z planu: dwa uruchomienia z tego samego commitu, inna zależność.

    Bez tego commit opisywałby kod źródłowy, a nie to, co faktycznie policzyło liczbę.
    """
    przed = licz(silnik).identity.runtime_digest
    assert przed

    import app.services.fatigue_engine as modul
    prawdziwe = modul._wersje_zaleznosci

    def inne():
        d = dict(prawdziwe())
        d["scipy"] = "0.0.0-podmieniona"
        return d

    monkeypatch.setattr(modul, "_wersje_zaleznosci", inne)
    modul._runtime_digest.cache_clear()
    try:
        po = licz(FatigueEngine("fatigue_config.yaml")).identity.runtime_digest
    finally:
        modul._runtime_digest.cache_clear()
    assert po != przed, "inna wersja zależności dała ten sam ślad wykonawczy"


def test_slad_wykonawczy_jest_stabilny_miedzy_wywolaniami(silnik):
    """Ten sam artefakt daje ten sam ślad - inaczej każdy pomiar byłby nowym instrumentem."""
    a = licz(silnik).identity.runtime_digest
    b = licz(FatigueEngine("fatigue_config.yaml")).identity.runtime_digest
    assert a == b


def test_skrot_konfiguracji_to_bajty_pliku(silnik):
    """`instrument_hash` musi wiązać się z TREŚCIĄ pliku, nie z jego wersją semantyczną.

    Dwie konfiguracje o tym samym `version` i różnych wagach nie mogą dzielić skrótu.
    """
    import hashlib
    surowe = open("fatigue_config.yaml", "rb").read()
    assert licz(silnik).identity.instrument_hash == hashlib.sha256(surowe).hexdigest()
