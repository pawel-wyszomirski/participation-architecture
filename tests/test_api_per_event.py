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
    SourceReceipt, HEALTHY_COMPLETE, AUTH_MISSING, ELIGIBLE, NOT_ELIGIBLE, UNAVAILABLE, ERROR,
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
    return p


class _Fakes:
    """Mutable so a test can flip a source into failure."""
    snapshot_state = HEALTHY_COMPLETE
    eco_state = HEALTHY_COMPLETE
    taxonomy_state = HEALTHY_COMPLETE


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
    monkeypatch.setattr(main.SnapshotClient, "fetch_voted_observations", _snap)
    monkeypatch.setattr(main.SnapshotClient, "fetch_ecosystem_exposure", _eco)
    monkeypatch.setattr(main.TallyClient, "fetch_voted_observations", _tally)
    monkeypatch.setattr(main.GovernorClient, "fetch_voted_observations", _gov)
    monkeypatch.setattr(main.ArbdataClient, "load", _registry)
    yield


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
    assert {x["source"] for x in ident["source_receipts"]} == {"snapshot", "tally", "governor", "ecosystem", "taxonomy"}


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
