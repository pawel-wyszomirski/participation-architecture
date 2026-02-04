"""
Unit Tests for Rule Engine (Compatible with Rulebook v2.5.0)
Tests Context phases, Strict rules, Overrides, historical weight preservation,
all categories, modifiers, edge cases, and determinism.

Run with: pytest tests/rules/test_rule_engine.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.services.rule_engine import (
    RuleEngine,
    ProposalInput,
    TriageResult,
    create_test_proposal
)

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def engine():
    """
    Initialize rule engine with the v2.5.0 rulebook.
    """
    # Fallback logic for testing convenience
    filename = "rulebook_kimi.yaml" if os.path.exists("rulebook_kimi.yaml") else "rulebook.yaml"
    return RuleEngine(filename)

@pytest.fixture
def base_proposal():
    """Base proposal for testing"""
    return create_test_proposal(
        item_id="test_001",
        title="Test Proposal",
        body="Test body content",
        status="active"
    )

# ============================================================================
# TEST: ENGINE INITIALIZATION
# ============================================================================

def test_engine_loads_rulebook_v2_5(engine):
    """Test that rule engine loads v2.5.0 rulebook successfully"""
    assert engine is not None
    assert engine.version == "2.5.0"
    assert len(engine.rulebook["rules"]) >= 20 

# ============================================================================
# TEST: PHASE 0 & 1 - CONTEXT & CRITICAL SECURITY (SEC-001-STRICT)
# ============================================================================

def test_sec_001_strict_active_incident(engine):
    """SEC-001-STRICT: Active exploit keywords -> EMERGENCY + Score >= 95"""
    proposal = create_test_proposal(
        title="Urgent: Active Exploit Detected",
        body="The bridge is compromised and funds are being drained. Immediate pause required."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-001-STRICT" in result.reasons
    assert "INCIDENT" in result.labels
    assert "EMERGENCY" in result.labels
    assert result.priority_score >= 95
    assert result.recommended_handling == "urgent_deep_review"

def test_sec_001_strict_negative(engine):
    """SEC-001-STRICT: Generic security words without active threat -> Should NOT fire"""
    proposal = create_test_proposal(
        title="Security discussion",
        body="We should discuss future security parameters."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-001-STRICT" not in result.reasons
    assert "INCIDENT" not in result.labels

# ============================================================================
# TEST: PHASE 2 - TECHNICAL & PROTOCOL (TECH-001, TECH-002)
# ============================================================================

def test_tech_001_protocol_upgrade(engine):
    """TECH-001-STRICT: Upgrade keywords -> PROTOCOL_UPGRADE label"""
    proposal = create_test_proposal(
        title="ArbOS Version 2.0 Upgrade",
        body="Deploying new hard fork and sequencer upgrade to mainnet."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-001-STRICT" in result.reasons
    assert "PROTOCOL_UPGRADE" in result.labels
    assert result.priority_score >= 80

def test_tech_002_parameter_change(engine):
    """TECH-002: Parameter keywords -> PARAMETER_CHANGE label"""
    proposal = create_test_proposal(
        title="Adjust Base Fee Parameters",
        body="Proposing a fee adjustment and gas target change."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-002" in result.reasons
    assert "PARAMETER_CHANGE" in result.labels
    assert result.priority_score >= 70

# ============================================================================
# TEST: TREASURY RULES (TRE-010, TRE-021)
# ============================================================================

def test_tre_010_tier_1_allocation(engine):
    """TRE-010: >$10M -> TREASURY_TIER_1 (Score >= 85)"""
    proposal = create_test_proposal(
        title="Ecosystem Fund Allocation",
        body="Requesting funding for yearly operations.",
        requested_amount_usd=15_000_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-010" in result.reasons
    assert "TREASURY_TIER_1" in result.labels
    assert result.priority_score >= 85

def test_tre_010_tier_2_allocation(engine):
    """TRE-010: >$1M -> TREASURY_TIER_2 (Score >= 75)"""
    proposal = create_test_proposal(
        title="Medium Grant",
        body="Funding request.",
        requested_amount_usd=5_000_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-010" in result.reasons
    assert "TREASURY_TIER_2" in result.labels
    assert result.priority_score >= 75

def test_tre_010_tier_3_allocation(engine):
    """TRE-010: >$100k -> TREASURY_TIER_3 (Score >= 60)"""
    proposal = create_test_proposal(
        title="Defi Grant",
        body="Grant for liquidity provision.",
        requested_amount_usd=250_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-010" in result.reasons
    assert "TREASURY_TIER_3" in result.labels
    assert result.priority_score >= 60

def test_tre_021_treasury_keywords_no_amount(engine):
    """TRE-021: Treasury keywords without explicit amount -> BUDGET_UNCLEAR"""
    proposal = create_test_proposal(
        title="Budget Framework Discussion",
        body="Discussing budget request and compensation structure for the DAO."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-021" in result.reasons
    assert "BUDGET_UNCLEAR" in result.labels
    assert result.priority_score >= 45

# ============================================================================
# TEST: GOVERNANCE & STRATEGY (GOV-030, PROG-001)
# ============================================================================

def test_gov_030_constitutional(engine):
    """GOV-030: Constitution keywords -> GOVERNANCE_FRAMEWORK"""
    proposal = create_test_proposal(
        title="Amend DAO Constitution",
        body="Updating the bylaws and governance framework."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "GOV-030" in result.reasons
    assert "GOVERNANCE_FRAMEWORK" in result.labels
    assert result.priority_score >= 75

def test_prog_001_new_program(engine):
    """PROG-001: New program keywords -> NEW_PROGRAM label"""
    proposal = create_test_proposal(
        title="Launch Incentive Program Pilot",
        body="Designing a new initiative for developer adoption."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "PROG-001" in result.reasons
    assert "NEW_PROGRAM" in result.labels
    assert result.priority_score >= 70

# ============================================================================
# TEST: OTHER CATEGORIES (META, SPON, REP, RES, OPS)
# ============================================================================

def test_meta_001_rfc(engine):
    """META-001: Discussion/RFC keywords -> META_GOV (Max 50)"""
    proposal = create_test_proposal(
        title="RFC: Community Gathering",
        body="Temperature check for the next meetup location."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "META-001" in result.reasons
    assert "META_GOV" in result.labels
    assert result.priority_score <= 50

def test_spon_001_sponsorship(engine):
    """SPON-001: Sponsorship keywords -> SPONSORSHIP label"""
    proposal = create_test_proposal(
        title="EthDenver Sponsorship",
        body="Proposal to sponsor the hackathon event."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SPON-001" in result.reasons
    assert "SPONSORSHIP" in result.labels
    assert result.priority_score <= 60

def test_rep_001_strict_reporting(engine):
    """REP-001-STRICT: Reporting keywords -> REPORTING (Max 35)"""
    proposal = create_test_proposal(
        title="Monthly Transparency Report",
        body="Summary of financial activities and progress update."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "REP-001-STRICT" in result.reasons
    assert "REPORTING" in result.labels
    assert result.priority_score <= 35

def test_res_001_research(engine):
    """RES-001: Research keywords -> RESEARCH (Max 40)"""
    proposal = create_test_proposal(
        title="Research Study on L2 Fees",
        body="Analysis of fee markets and comparative study."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "RES-001" in result.reasons
    assert "RESEARCH" in result.labels
    assert result.priority_score <= 40

def test_ops_050_operational(engine):
    """OPS-050: Operational keywords -> OPERATIONS (Max 45)"""
    proposal = create_test_proposal(
        title="Renewal of Admin Services",
        body="Routine maintenance and housekeeping tasks."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "OPS-050" in result.reasons
    assert "OPERATIONS" in result.labels
    assert result.priority_score <= 45

# ============================================================================
# TEST: CONTEXT DETECTION (CTX-002, CTX-003)
# ============================================================================

def test_ctx_002_election_context(engine):
    """CTX-002: Election keywords -> ELECTIONS label + Context Flag"""
    proposal = create_test_proposal(
        title="Security Council Election Nomination",
        body="Candidate for the open seat."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "CTX-002" in result.reasons
    assert "ELECTIONS" in result.labels

def test_ctx_003_hr_context(engine):
    """CTX-003: Salary/Compensation keywords -> OPERATIONS + BUDGET"""
    proposal = create_test_proposal(
        title="Contributor Compensation Payment",
        body="Monthly salary and stipend distribution."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "CTX-003" in result.reasons
    assert "OPERATIONS" in result.labels
    assert "BUDGET" in result.labels

# ============================================================================
# TEST: OVERRIDES & HISTORICAL PRESERVATION (PHASE 4)
# ============================================================================

def test_override_closed_critical_protocol(engine):
    """OVERRIDE-CLOSED-PROTOCOL: Closed Protocol Upgrade -> High Score (Deep Review)"""
    proposal = create_test_proposal(
        title="ArbOS v1 Upgrade (Executed)",
        body="Major protocol change including sequencer upgrade.",
        status="executed"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    # CTX-001 sets STATE_CLOSED flag
    # TECH-001 sets PROTOCOL_UPGRADE
    # OVERRIDE-CLOSED-PROTOCOL should fire
    assert "CTX-001" in result.reasons
    assert "TECH-001-STRICT" in result.reasons
    assert "OVERRIDE-CLOSED-PROTOCOL" in result.reasons
    
    # Should maintain high score despite being closed
    assert result.priority_score >= 65
    assert result.recommended_handling == "deep_review"

def test_override_closed_general_kill_switch(engine):
    """OVERRIDE-CLOSED-01: Closed minor proposal -> Standard Review (max 50)"""
    proposal = create_test_proposal(
        title="Old Operations Update",
        body="Routine housekeeping tasks from last year.",
        status="expired"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "CTX-001" in result.reasons
    assert "OPS-050" in result.reasons
    assert "OVERRIDE-CLOSED-01" in result.reasons
    
    assert result.priority_score <= 50
    assert result.recommended_handling == "standard_review"

def test_override_closed_election(engine):
    """OVERRIDE-CLOSED-02: Closed Election -> Informational Only (max 30)"""
    proposal = create_test_proposal(
        title="Past Council Election",
        body="Nomination and voting for last epoch.",
        status="executed"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "CTX-002" in result.reasons # Election context
    assert "OVERRIDE-CLOSED-02" in result.reasons
    
    assert result.priority_score <= 30
    assert result.recommended_handling == "informational_only"

# ============================================================================
# TEST: MODIFIERS (TIME & WORKLOAD)
# ============================================================================

def test_time_modifiers_urgent(engine):
    """TIME-MODIFIERS: <24h remaining -> +15 Priority"""
    now = datetime.now(timezone.utc)
    proposal = create_test_proposal(
        title="Urgent Proposal",
        body="Content",
        status="active",
        end_at=int((now + timedelta(hours=12)).timestamp())
    )
    
    result = engine.evaluate_proposal(proposal)
    assert "TIME-MODIFIERS" in result.reasons
    # Cannot easily check exact increment without mocking, but we verify rule fired

def test_time_modifiers_upcoming(engine):
    """TIME-MODIFIERS: 48-72h remaining -> +5 Priority"""
    now = datetime.now(timezone.utc)
    proposal = create_test_proposal(
        title="Upcoming Proposal",
        body="Content",
        status="active",
        end_at=int((now + timedelta(hours=60)).timestamp())
    )
    
    result = engine.evaluate_proposal(proposal)
    assert "TIME-MODIFIERS" in result.reasons

def test_workload_modifiers_long(engine):
    """WORKLOAD-MODIFIERS: Long text (>3000) -> LONG_FORM label"""
    long_body = "word " * 3500
    proposal = create_test_proposal(
        title="Long Manifesto",
        body=long_body,
        word_count=3500
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "WORKLOAD-MODIFIERS" in result.reasons
    assert "LONG_FORM" in result.labels

def test_workload_modifiers_very_long(engine):
    """WORKLOAD-MODIFIERS: Very long text (>5000) -> VERY_LONG_FORM label"""
    long_body = "word " * 5500
    proposal = create_test_proposal(
        title="Huge Manifesto",
        body=long_body,
        word_count=5500
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "WORKLOAD-MODIFIERS" in result.reasons
    assert "VERY_LONG_FORM" in result.labels

# ============================================================================
# TEST: DEFAULT FALLBACK
# ============================================================================

def test_default_classification(engine):
    """DEFAULT-001: No matches -> UNCATEGORIZED"""
    proposal = create_test_proposal(
        title="Something completely random",
        body="No keywords here just fluff."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "DEFAULT-001" in result.reasons
    assert "UNCATEGORIZED" in result.labels
    assert 30 <= result.priority_score <= 50

# ============================================================================
# TEST: EDGE CASES
# ============================================================================

def test_empty_body_proposal(engine):
    """Test proposal with empty body doesn't crash"""
    proposal = create_test_proposal(
        title="Title Only",
        body=""
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert result is not None
    assert result.priority_score >= 0

def test_very_long_title(engine):
    """Test proposal with extremely long title"""
    long_title = "A" * 1000  # 1000 character title
    proposal = create_test_proposal(
        title=long_title,
        body="Content"
    )
    
    result = engine.evaluate_proposal(proposal)
    assert result is not None

def test_null_optional_fields(engine):
    """Test proposal with all optional fields as None"""
    # Create raw object to bypass helper defaults if needed,
    # or just use helper with explicit Nones where allowed.
    proposal = ProposalInput(
        item_id="null_test",
        title="Minimal Proposal",
        body="Content",
        author="unknown",
        created_at=int(datetime.now(timezone.utc).timestamp()),
        start_at=int(datetime.now(timezone.utc).timestamp()),
        end_at=int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
        status="active"
    )
    
    result = engine.evaluate_proposal(proposal)
    assert result is not None

# ============================================================================
# TEST: DETERMINISM
# ============================================================================

def test_determinism_same_input_same_output(engine):
    """Test that same proposal always produces same result"""
    proposal = create_test_proposal(
        title="Determinism Test",
        body="Testing reproducibility.",
        requested_amount_usd=500_000
    )
    
    result1 = engine.evaluate_proposal(proposal)
    result2 = engine.evaluate_proposal(proposal)
    
    assert result1.priority_score == result2.priority_score
    assert result1.labels == result2.labels
    assert result1.reasons == result2.reasons
    assert result1.recommended_handling == result2.recommended_handling

# ============================================================================
# RUN SUMMARY
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])