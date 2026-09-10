"""
Endpoint tests for closure review point 5 (/t/30604, 2026-09-03):
GET /delegates/{address}/per-event-fatigue must not persist anything, POST on
the same path registers exactly one row per complete measurement identity.

<!-- catalog-read --> tests/ had no endpoint test for the per-event route;
test_governor_client covers the chain client only.

The three source clients and the DAO registry are replaced with in-memory
fakes - these tests exercise the HTTP layer and persistence, not the network.

Run with: pytest tests/test_api_per_event.py -v
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# A throwaway SQLite file BEFORE app.main creates its engine.
_TMP = tempfile.mkdtemp(prefix="pa-api-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/api-test.db"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.db.models import FatigueSnapshot, Proposal  # noqa: E402
from app.services.fatigue_engine import (  # noqa: E402
    SourceReceipt, HEALTHY_COMPLETE, HEALTHY_EMPTY, AUTH_MISSING, ELIGIBLE, NOT_ELIGIBLE,
    UNAVAILABLE, ERROR,
)

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
ADDR = "0x00000000000000000000000000000000000000aa"


def _obs(id_, days_ago, title="Proposal", body="word " * 300, domain="snapshot"):
    t = int((NOW - timedelta(days=days_ago)).timestamp())
    p = Proposal(id=id_, title=title, body=body, state="closed", start=t, end=t + 3 * 86400)
    p.voted_at = t
    p.source = domain
    p.source_domain = domain
    p.source_vote_id = f"v-{id_}"
    p.native_proposal_id = id_
    p.voter = ADDR
    p.cast_at = t
    # Kategoria z taksonomii - WARTOŚĆ rekordu, nie jego identyfikator. Test tożsamości
    # zmienia ją przy niezmienionych identyfikatorach (regresja kontrprzykładu z 09.09).
    p.category = _Fakes.category
    return p


class _Fakes:
    """Mutable so a test can flip a source into failure."""
    snapshot_state = HEALTHY_COMPLETE
    eco_state = HEALTHY_COMPLETE
    taxonomy_state = HEALTHY_COMPLETE
    eco_gov_state = HEALTHY_COMPLETE
    category = "treasury"


async def _snap(self, address, limit=200, **kw):
    if _Fakes.snapshot_state != HEALTHY_COMPLETE:
        return [], SourceReceipt("snapshot", _Fakes.snapshot_state, detail="fake")
    return ([_obs("snap-1", 0, title="Target"), _obs("snap-2", 4, title="Earlier")],
            SourceReceipt("snapshot", HEALTHY_COMPLETE, events=2))


async def _tally(self, address, limit=200):
    return [], SourceReceipt("tally", AUTH_MISSING, detail="no key")


async def _gov(self, address, days=120, limit=200):
    return ([_obs("governor:core:9", 9, title="Onchain", domain="governor:core")],
            SourceReceipt("governor", HEALTHY_COMPLETE, events=1))


async def _eco(self, at_ts, space=None):
    if _Fakes.eco_state != HEALTHY_COMPLETE:
        return None, SourceReceipt("ecosystem", _Fakes.eco_state, detail="fake")
    return [_obs("eco-1", 1)], SourceReceipt("ecosystem", HEALTHY_COMPLETE, events=1)


async def _eco_gov(self, at_ts, days_back=120):
    """Ekspozycja z warstwy KONTRAKTOWEJ (I3, 2026-09-09).

    Atrapa jest konieczna, nie kosmetyczna: bez niej testy wychodzą do publicznych węzłów
    RPC - suita rosła z 6 do 46 sekund, a wynik zależał od stanu sieci. Test, który pyta
    prawdziwy łańcuch, mierzy łańcuch, nie kod.
    """
    if _Fakes.eco_gov_state != HEALTHY_COMPLETE:
        return None, SourceReceipt("ecosystem_governor", _Fakes.eco_gov_state, detail="fake")
    return [], SourceReceipt("ecosystem_governor", HEALTHY_EMPTY, events=0)


async def _registry(self):
    """The DAO registry is a source with a receipt too (production 2026-09-04:
    it answered 403 and the verdict stayed clean)."""
    self.receipt = SourceReceipt("taxonomy", _Fakes.taxonomy_state,
                                 detail="fake" if _Fakes.taxonomy_state != HEALTHY_COMPLETE else "")
    return 0


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    _Fakes.snapshot_state = HEALTHY_COMPLETE
    _Fakes.eco_state = HEALTHY_COMPLETE
    _Fakes.taxonomy_state = HEALTHY_COMPLETE
    _Fakes.eco_gov_state = HEALTHY_COMPLETE
    monkeypatch.setattr(main.SnapshotClient, "fetch_voted_observations", _snap)
    monkeypatch.setattr(main.SnapshotClient, "fetch_ecosystem_exposure", _eco)
    monkeypatch.setattr(main.TallyClient, "fetch_voted_observations", _tally)
    monkeypatch.setattr(main.GovernorClient, "fetch_voted_observations", _gov)
    monkeypatch.setattr(main.GovernorClient, "fetch_ecosystem_exposure", _eco_gov)
    monkeypatch.setattr(main.ArbdataClient, "load", _registry)
    yield
    # Baza jest wspólna dla całego pliku, więc wiersz zostawiony przez jeden test
    # rozstrzygał o wyniku następnego: test sprawdzający konflikt CELOWO psuje zapis,
    # a kolejny dostawał przez to 409, badając coś zupełnie innego. Sprzątanie stoi tu,
    # a nie w `finally` pojedynczych testów, bo wykona się także po nieudanej asercji
    # - inaczej pierwsza porażka zatruwa całą resztę pliku i przyczyna wygląda na
    # kilka usterek naraz. Kolejność zbierania nie ma prawa rozstrzygać o wyniku.
    with main.SessionLocal() as db:
        db.query(FatigueSnapshot).delete()
        db.commit()


@pytest.fixture
def client():
    return TestClient(main.app)


def _rows():
    db = main.SessionLocal()
    try:
        return db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id.isnot(None)).all()
    finally:
        db.close()


def test_get_computes_but_never_persists(client):
    before = len(_rows())
    for _ in range(3):
        r = client.get(f"/delegates/{ADDR}/per-event-fatigue")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["persisted"] is None
        assert body["eligibility"] == ELIGIBLE
        assert body["measurement_id"]
    assert len(_rows()) == before


def test_post_registers_once_per_measurement_identity(client):
    before = len(_rows())
    first = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    second = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    third = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    assert first["persisted"] is True
    assert second["persisted"] is False
    assert third["persisted"] is False
    assert first["measurement_id"] == second["measurement_id"] == third["measurement_id"]
    rows = _rows()
    assert len(rows) == before + 1
    row = next(r for r in rows if r.measurement_id == first["measurement_id"])
    assert row.eligibility == ELIGIBLE
    assert row.instrument_hash == main.fatigue_engine.instrument_hash
    assert '"source_receipts"' in row.manifest
    assert '"lifecycle_id"' in row.manifest


def test_changed_input_set_is_a_new_measurement(client):
    a = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    _Fakes.eco_state = UNAVAILABLE      # ecosystem source stops answering
    b = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    assert a["measurement_id"] != b["measurement_id"]
    assert b["eligibility"] == NOT_ELIGIBLE
    assert b["metrics"]["concurrency_source"] == "voted_only"
    assert any("construct" in x for x in b["identity"]["eligibility_reasons"])


def test_target_by_stage_id_and_identity_fields(client):
    r = client.get(f"/delegates/{ADDR}/per-event-fatigue", params={"proposal_id": "governor:core:9"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_proposal_id"] == "governor:core:9"
    ident = body["identity"]
    assert ident["stage_ids"] == ["governor:core:9"]
    assert ident["source_domain"] == "governor:core"
    assert ident["source_vote_id"] == "v-governor:core:9"
    # `ecosystem_governor` doszło 2026-09-09 (I3): ekspozycja czyta OBIE warstwy, bo
    # od czerwca 2026 wiążące głosowania są na kontrakcie, a sama warstwa Snapshot dawała
    # `concurrency` = 0 dla każdego świeżego głosu.
    assert {x["source"] for x in ident["source_receipts"]} == {
        "snapshot", "tally", "governor", "ecosystem", "ecosystem_governor", "taxonomy"}


def test_required_source_failure_is_visible_and_disqualifies(client):
    _Fakes.snapshot_state = UNAVAILABLE
    r = client.get(f"/delegates/{ADDR}/per-event-fatigue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligibility"] == NOT_ELIGIBLE
    assert any("snapshot" in x and "UNAVAILABLE" in x for x in body["identity"]["eligibility_reasons"])


def test_invalid_instrument_answers_503_instrument_invalid(client, monkeypatch):
    monkeypatch.setattr(main, "fatigue_engine", None)
    monkeypatch.setattr(main, "fatigue_engine_error", "INSTRUMENT_INVALID: weights sum to 1.350")
    r = client.get(f"/delegates/{ADDR}/per-event-fatigue")
    assert r.status_code == 503
    assert "INSTRUMENT_INVALID" in r.json()["detail"]
    p = client.post(f"/delegates/{ADDR}/per-event-fatigue")
    assert p.status_code == 503


def test_taxonomy_registry_failure_is_visible_and_disqualifies(client):
    """Production 2026-09-04: arbdata answered 403, novelty 0.0, verdict clean.
    The registry's receipt must reach the verdict."""
    _Fakes.taxonomy_state = ERROR
    r = client.get(f"/delegates/{ADDR}/per-event-fatigue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["eligibility"] == NOT_ELIGIBLE
    assert any("taxonomy" in x for x in body["identity"]["eligibility_reasons"])

def test_ponowna_rejestracja_oddaje_zapisany_wiersz_nie_swiezy_wynik(client):
    """I2 (2026-09-09): POST przy istniejącym identyfikatorze zwraca ZAPISANY pomiar.

    Do 09.09 zwracany był wynik przeliczony przed chwilą (`main.py:813`), więc rejestr mógł
    trzymać jedną liczbę, a wołający dostawał inną - obie pod jednym `measurement_id`.
    Test sabotuje wiersz w bazie po pierwszej rejestracji i sprawdza, czym odpowiada API.
    """
    # Testy dzielą bazę, więc wiersz mógł powstać we wcześniejszym teście - liczy się to,
    # że po tym wywołaniu istnieje, nie kto go założył.
    pierwszy = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    mid = pierwszy["measurement_id"]
    assert mid

    # Podmiana zapisanego wyniku na wartość, której silnik nie policzy - odpowiedź
    # zbudowana z wiersza musi ją oddać, odpowiedź z przeliczenia nie zna jej wcale.
    with main.SessionLocal() as db:
        row = db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id == mid).first()
        row.fatigue_score = pierwszy["fatigue_score"]      # zgodny, żeby nie wywołać 409
        row.status = "SABOTAZ"
        row.comp_novelty = 0.4242
        db.commit()

    drugi = client.post(f"/delegates/{ADDR}/per-event-fatigue")

    # ZMIANA WARUNKU 10.09, po wzmocnieniu kontraktu zapisu.
    # Do dziś porównywany był sam `fatigue_score`, więc wiersz z podmienionym statusem
    # i składnikiem przechodził jako zgodny, a test sprawdzał, czy odpowiedź niesie
    # zapisane wartości. Teraz porównanie obejmuje CAŁY wynik kanoniczny, więc taki
    # rozjazd jest tym, czym jest: naruszeniem tożsamości, nie stanem do oddania
    # wołającemu. Sytuacja „odpowiedź z wiersza różni się od przeliczenia" nie może już
    # zaistnieć - albo wartości są zgodne, albo leci 409.
    # Ochrona przed I2 nie znika, tylko zmienia miejsce: skoro każdy rozjazd kończy się
    # konfliktem, nie da się oddać świeżego wyniku udającego zapisany.
    assert drugi.status_code == 409
    detail = drugi.json()["detail"]
    assert detail["error"] == "MEASUREMENT_IDENTITY_CONFLICT"
    rozjechane = {r["pole"] for r in detail["rozjazdy"]}
    assert rozjechane == {"status", "novelty"}, (
        f"konflikt ma nazywać KTÓRE pola się rozjechały, dostałam: {detail['rozjazdy']}")

    with main.SessionLocal() as db:
        db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id == mid).delete()
        db.commit()


def test_rozbieznosc_zapisanego_i_przeliczonego_konczy_sie_konfliktem(client):
    """Ta sama tożsamość przy innym wyniku jest naruszeniem kontraktu, nie sytuacją do
    wygładzenia. Ciche oddanie starego wiersza schowałoby dokładnie ten defekt, którego
    szukamy - dlatego rozbieżność kończy się 409, z obiema liczbami w treści."""
    pierwszy = client.post(f"/delegates/{ADDR}/per-event-fatigue").json()
    mid = pierwszy["measurement_id"]
    with main.SessionLocal() as db:
        row = db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id == mid).first()
        row.fatigue_score = (pierwszy["fatigue_score"] or 0) + 7.0
        db.commit()

    odp = client.post(f"/delegates/{ADDR}/per-event-fatigue")
    assert odp.status_code == 409
    detail = odp.json()["detail"]
    assert detail["error"] == "MEASUREMENT_IDENTITY_CONFLICT"
    assert detail["persisted_score"] != detail["recomputed_score"]

    # Ten test CELOWO psuje zapisany wiersz, więc musi po sobie posprzątać: bez tego
    # każdy późniejszy test rejestrujący ten sam pomiar dziedziczy konflikt i pada
    # z 409, choć sprawdza coś zupełnie innego. Tak padał
    # `test_post_zapisuje_wejscie_do_odtworzenia_offline` - w izolacji przechodził,
    # w suicie nie. Baza jest wspólna dla całego pliku, a kolejność zbierania nie
    # ma prawa rozstrzygać o wyniku (`tests/conftest.py`, zasada z CLAUDE.md).
    with main.SessionLocal() as db:
        db.query(FatigueSnapshot).filter(FatigueSnapshot.measurement_id == mid).delete()
        db.commit()


def test_tozsamosc_wiaze_wartosci_wejsc_nie_identyfikatory(client):
    """I1 (2026-09-09): kontrprzykład z sekcji 8a analizy, jako regresja.

    Schemat 1 hashował zbiory identyfikatorów, więc zmiana WARTOŚCI rekordu przy tych samych
    identyfikatorach dawała jeden `measurement_id` i dwa różne wyniki (44,90 i 46,60 pod
    `83df5f4f2301ef52b6b98551f1ae9bea`). Schemat 2 hashuje projekcję wartości.
    """
    a = client.get(f"/delegates/{ADDR}/per-event-fatigue").json()
    assert a["identity"]["identity_schema_version"], "brak wersji schematu tożsamości"
    assert a["identity"]["canonical_input_digest"], "brak skrótu projekcji wartości"

    stara_kategoria = _Fakes.category
    try:
        _Fakes.category = "inna-kategoria-tego-samego-rekordu"
        b = client.get(f"/delegates/{ADDR}/per-event-fatigue").json()
    finally:
        _Fakes.category = stara_kategoria

    if b["fatigue_score"] != a["fatigue_score"]:
        assert b["measurement_id"] != a["measurement_id"], (
            "ten sam identyfikator przy różnym wyniku - kontrakt tożsamości naruszony")


def test_post_zapisuje_wejscie_do_odtworzenia_offline(client, monkeypatch):
    import json
    from app.services.fatigue_engine import FatigueEngine

    response = client.post(f"/delegates/{ADDR}/per-event-fatigue")
    assert response.status_code == 200
    body = response.json()
    row = next(r for r in _rows() if r.measurement_id == body['measurement_id'])
    manifest = json.loads(row.manifest)
    assert manifest['prepared_input'] == body['identity']['prepared_input']
    assert manifest['prepared_input']['config']['reference_values_per_event']['reading_words'] == 710
    monkeypatch.setattr(FatigueEngine, '_load_config', lambda self: pytest.fail('odczyt YAML'))
    restored = FatigueEngine.replay(manifest)
    assert restored.fatigue_score == row.fatigue_score
    assert restored.components.novelty == row.comp_novelty
    assert restored.identity.measurement_id == row.measurement_id
    assert restored.identity.input_conflicts == manifest['input_conflicts']
