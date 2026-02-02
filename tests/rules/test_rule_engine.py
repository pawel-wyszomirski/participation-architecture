"""
Unit Tests for Rule Engine
Tests all 21 rules, condition matchers, conflict resolution, and edge cases

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
    """Initialize rule engine with rulebook.yaml"""
    return RuleEngine("rulebook.yaml")


@pytest.fixture
def base_proposal():
    """Base proposal for testing"""
    return create_test_proposal(
        item_id="test_001",
        title="Test Proposal",
        body="Test body content",
        status="active"
    )


@pytest.fixture
def active_proposal_near_deadline():
    """Proposal with 12 hours until deadline"""
    now = datetime.now(timezone.utc)
    return create_test_proposal(
        item_id="deadline_001",
        title="Urgent Deadline",
        body="Content",
        status="active",
        start_at=int((now - timedelta(days=5)).timestamp()),
        end_at=int((now + timedelta(hours=12)).timestamp())  # 12h remaining
    )


# ============================================================================
# TEST: ENGINE INITIALIZATION
# ============================================================================

def test_engine_loads_rulebook(engine):
    """Test that rule engine loads rulebook successfully"""
    assert engine is not None
    assert engine.version == "1.0.0"
    assert len(engine.rulebook["rules"]) == 21
    assert len(engine.rulebook["keyword_groups"]) == 9


def test_engine_info(engine):
    """Test get_rulebook_info method"""
    info = engine.get_rulebook_info()
    assert info["version"] == "1.0.0"
    assert info["num_rules"] == 21
    assert info["num_keyword_groups"] == 9


# ============================================================================
# TEST: SECURITY RULES (SEC-001, SEC-002)
# ============================================================================

def test_sec_001_emergency_cues_multiple_keywords(engine):
    """SEC-001: Multiple security keywords → SECURITY label + score ≥90"""
    proposal = create_test_proposal(
        title="Emergency: Critical Exploit Found",
        body="A vulnerability was discovered leading to a potential hack attack."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-001" in result.reasons
    assert "SECURITY" in result.labels
    assert "INCIDENT" in result.labels
    assert result.priority_score >= 90
    assert result.recommended_handling == "urgent_deep_review"


def test_sec_001_security_plus_upgrade_keyword(engine):
    """SEC-001: Security + upgrade keyword → Fires"""
    proposal = create_test_proposal(
        title="Security patch for protocol upgrade",
        body="Deploying critical security fix."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-001" in result.reasons
    assert "SECURITY" in result.labels


def test_sec_001_negative_no_security_keywords(engine):
    """SEC-001: No security keywords → Should NOT fire"""
    proposal = create_test_proposal(
        title="Regular Treasury Allocation",
        body="Budget for Q1 operations."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-001" not in result.reasons
    assert "SECURITY" not in result.labels


def test_sec_002_audit_vulnerability(engine):
    """SEC-002: Audit + vulnerability → SECURITY + AUDIT labels"""
    proposal = create_test_proposal(
        title="Audit Report: Critical Vulnerability",
        body="Security audit found critical issues requiring immediate attention."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "SEC-002" in result.reasons
    assert "SECURITY" in result.labels
    assert "AUDIT" in result.labels
    assert result.priority_score >= 85


# ============================================================================
# TEST: TECHNICAL RULES (TECH-010, TECH-011)
# ============================================================================

def test_tech_010_protocol_upgrade_keywords(engine):
    """TECH-010: Multiple upgrade keywords → PROTOCOL_UPGRADE label"""
    proposal = create_test_proposal(
        title="Protocol Upgrade v2.0",
        body="Deploy new version with rollup improvements and sequencer updates."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-010" in result.reasons
    assert "PROTOCOL_UPGRADE" in result.labels
    assert result.priority_score >= 80


def test_tech_010_technical_proposal_kind(engine):
    """TECH-010: proposal_kind=technical → Fires"""
    proposal = create_test_proposal(
        title="Smart Contract Update",
        body="Technical changes to core contracts.",
        proposal_kind="technical"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-010" in result.reasons
    assert "PROTOCOL_UPGRADE" in result.labels


def test_tech_011_parameter_change_keywords(engine):
    """TECH-011: Parameter keywords → PARAMETER_CHANGE label"""
    proposal = create_test_proposal(
        title="Adjust Gas Limit and Fee Parameters",
        body="Proposing to change gas threshold and rate configuration."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-011" in result.reasons
    assert "PARAMETER_CHANGE" in result.labels
    assert result.priority_score >= 75


def test_tech_011_affects_protocol_parameters_field(engine):
    """TECH-011: affects_protocol_parameters=true → Fires"""
    proposal = create_test_proposal(
        title="Parameter Adjustment",
        body="Minor config change.",
        affects_protocol_parameters=True
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TECH-011" in result.reasons
    assert "PARAMETER_CHANGE" in result.labels


# ============================================================================
# TEST: TREASURY RULES (TRE-020, TRE-021)
# ============================================================================

def test_tre_020_large_treasury_10m(engine):
    """TRE-020: $10M+ allocation → Tier 1 (score ≥85)"""
    proposal = create_test_proposal(
        title="Major Treasury Allocation",
        body="Requesting large funding.",
        requested_amount_usd=15_000_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-020" in result.reasons
    assert "TREASURY" in result.labels
    assert "TREASURY_TIER_1" in result.labels
    assert result.priority_score >= 85


def test_tre_020_medium_treasury_1m(engine):
    """TRE-020: $1M-10M allocation → Tier 2 (score ≥75)"""
    proposal = create_test_proposal(
        title="Treasury Q1 Allocation",
        body="Quarterly budget.",
        requested_amount_usd=5_000_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-020" in result.reasons
    assert "TREASURY" in result.labels
    assert "TREASURY_TIER_2" in result.labels
    assert result.priority_score >= 75


def test_tre_020_small_treasury_100k(engine):
    """TRE-020: $100K-1M allocation → Tier 3 (score ≥65)"""
    proposal = create_test_proposal(
        title="Grant Program Funding",
        body="Small grants allocation.",
        requested_amount_usd=250_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-020" in result.reasons
    assert "TREASURY_TIER_3" in result.labels
    assert result.priority_score >= 65


def test_tre_020_tiny_treasury_10k(engine):
    """TRE-020: $10K-100K allocation → Tier 4 (score ≥55)"""
    proposal = create_test_proposal(
        title="Minor Expense Approval",
        body="Small operational cost.",
        requested_amount_usd=25_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-020" in result.reasons
    assert "TREASURY_TIER_4" in result.labels
    assert result.priority_score >= 55


def test_tre_021_treasury_keywords_no_amount(engine):
    """TRE-021: Treasury keywords but no amount → Baseline priority"""
    proposal = create_test_proposal(
        title="Budget Planning Discussion",
        body="Discussing allocation strategy and funding priorities for treasury management."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TRE-021" in result.reasons
    assert "TREASURY" in result.labels
    assert "BUDGET" in result.labels
    assert result.priority_score >= 55


# ============================================================================
# TEST: GOVERNANCE RULES (GOV-030, GOV-031)
# ============================================================================

def test_gov_030_constitutional_proposal_kind(engine):
    """GOV-030: proposal_kind=constitutional → GOVERNANCE_FRAMEWORK"""
    proposal = create_test_proposal(
        title="Constitution Amendment",
        body="Updating governance charter.",
        proposal_kind="constitutional"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "GOV-030" in result.reasons
    assert "GOVERNANCE_FRAMEWORK" in result.labels
    assert result.priority_score >= 70


def test_gov_030_framework_keywords(engine):
    """GOV-030: Multiple framework keywords → Fires"""
    proposal = create_test_proposal(
        title="AIP Framework Update",
        body="Revising the constitution and bylaws for improved governance."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "GOV-030" in result.reasons
    assert "GOVERNANCE_FRAMEWORK" in result.labels


def test_gov_031_quorum_voting_procedure(engine):
    """GOV-031: Quorum + voting procedure changes → High priority"""
    proposal = create_test_proposal(
        title="Adjust Quorum Threshold",
        body="Proposing to change quorum parameter and voting procedure configuration."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "GOV-031" in result.reasons
    assert "GOVERNANCE_FRAMEWORK" in result.labels
    assert "POLICY" in result.labels
    assert result.priority_score >= 75


# ============================================================================
# TEST: ELECTIONS RULES (ELE-040)
# ============================================================================

def test_ele_040_election_keywords(engine):
    """ELE-040: Election keywords → ELECTIONS label"""
    proposal = create_test_proposal(
        title="Security Council Election",
        body="Nomination period for delegate council candidates. Term renewal voting."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "ELE-040" in result.reasons
    assert "ELECTIONS" in result.labels
    assert result.priority_score >= 65


def test_ele_040_proposal_kind_election(engine):
    """ELE-040: proposal_kind=election → Fires"""
    proposal = create_test_proposal(
        title="Council Member Vote",
        body="Voting on new member.",
        proposal_kind="election"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "ELE-040" in result.reasons
    assert "ELECTIONS" in result.labels


# ============================================================================
# TEST: OPERATIONS & REPORTING RULES (OPS-050, REP-060, META-070)
# ============================================================================

def test_ops_050_operational_keywords(engine):
    """OPS-050: Operational keywords → OPERATIONS label + capped score"""
    proposal = create_test_proposal(
        title="Routine Housekeeping Tasks",
        body="Admin procedures for maintenance and operational calendar updates."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "OPS-050" in result.reasons
    assert "OPERATIONS" in result.labels
    assert result.priority_score <= 40


def test_ops_050_proposal_kind_ops(engine):
    """OPS-050: proposal_kind=ops → Capped at 40"""
    proposal = create_test_proposal(
        title="Minor Admin Task",
        body="Small operational update.",
        proposal_kind="ops"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "OPS-050" in result.reasons
    assert result.priority_score <= 40
    assert result.recommended_handling in ["fast_track_ok", "informational_only"]


def test_rep_060_reporting_keywords(engine):
    """REP-060: Reporting keywords → REPORTING label + capped at 30"""
    proposal = create_test_proposal(
        title="Monthly Status Report",
        body="Summary of weekly updates and metrics dashboard retrospective."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "REP-060" in result.reasons
    assert "REPORTING" in result.labels
    assert result.priority_score <= 30


def test_rep_060_title_contains_weekly_update(engine):
    """REP-060: Title contains 'weekly update' → Fires"""
    proposal = create_test_proposal(
        title="Weekly Update - Q1 Progress",
        body="Status report."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "REP-060" in result.reasons
    assert "REPORTING" in result.labels


def test_meta_070_discussion_type(engine):
    """META-070: item_type=discussion → META_GOV label + capped at 50"""
    proposal = create_test_proposal(
        title="Community Discussion",
        body="Open forum for feedback.",
        item_type="discussion"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "META-070" in result.reasons
    assert "META_GOV" in result.labels
    assert result.priority_score <= 50


def test_meta_070_temperature_check(engine):
    """META-070: Title contains 'temperature check' → Fires"""
    proposal = create_test_proposal(
        title="Temperature Check: New Feature",
        body="Gauging community interest."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "META-070" in result.reasons
    assert "META_GOV" in result.labels


# ============================================================================
# TEST: TIME MODIFIERS (TIME-001, TIME-002, TIME-003)
# ============================================================================

def test_time_001_critical_deadline_24h(engine):
    """TIME-001: ≤24h remaining → +15 priority"""
    now = datetime.now(timezone.utc)
    proposal = create_test_proposal(
        title="Urgent Vote",
        body="Time-sensitive decision.",
        status="active",
        end_at=int((now + timedelta(hours=12)).timestamp())  # 12h remaining
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TIME-001" in result.reasons
    # Check that +15 was added
    adjustments = result.explain["priority_adjustments"]
    time_adjustment = [a for a in adjustments if a["rule"] == "TIME-001"]
    assert len(time_adjustment) > 0


def test_time_002_near_deadline_48h(engine):
    """TIME-002: 24-48h remaining → +10 priority"""
    now = datetime.now(timezone.utc)
    proposal = create_test_proposal(
        title="Upcoming Deadline",
        body="Content.",
        status="active",
        end_at=int((now + timedelta(hours=36)).timestamp())  # 36h remaining
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TIME-002" in result.reasons


def test_time_003_upcoming_deadline_72h(engine):
    """TIME-003: 48-72h remaining → +5 priority"""
    now = datetime.now(timezone.utc)
    proposal = create_test_proposal(
        title="Approaching Deadline",
        body="Content.",
        status="active",
        end_at=int((now + timedelta(hours=60)).timestamp())  # 60h remaining
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TIME-003" in result.reasons


def test_time_010_closed_proposal_cap(engine):
    """TIME-010: Closed non-incident proposal → Capped at 50"""
    proposal = create_test_proposal(
        title="Past Proposal",
        body="Historical content.",
        status="closed"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "TIME-010" in result.reasons
    assert result.priority_score <= 50


def test_time_011_closed_reporting_cap(engine):
    """TIME-011: Closed + REPORTING label → Capped at 30"""
    proposal = create_test_proposal(
        title="Monthly Report Archive",
        body="Weekly update summary retrospective.",
        status="closed"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    # REP-060 should fire (adds REPORTING label)
    # TIME-011 should fire (caps at 30)
    assert "REP-060" in result.reasons
    assert "TIME-011" in result.reasons
    assert result.priority_score <= 30


# ============================================================================
# TEST: WORKLOAD MODIFIERS (LEN-001, LEN-002, LEN-003)
# ============================================================================

def test_len_001_long_form_3000_words(engine):
    """LEN-001: ≥3000 words → +10 priority + LONG_FORM label"""
    long_body = " ".join(["word"] * 3500)  # 3500 words
    proposal = create_test_proposal(
        title="Comprehensive Proposal",
        body=long_body,
        word_count=3500
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "LEN-001" in result.reasons
    assert "LONG_FORM" in result.labels


def test_len_002_medium_form_1500_words(engine):
    """LEN-002: 1500-3000 words → +6 priority + MEDIUM_FORM label"""
    medium_body = " ".join(["word"] * 2000)  # 2000 words
    proposal = create_test_proposal(
        title="Moderate Proposal",
        body=medium_body,
        word_count=2000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "LEN-002" in result.reasons
    assert "MEDIUM_FORM" in result.labels


def test_len_003_standard_form_800_words(engine):
    """LEN-003: 800-1500 words → +3 priority + STANDARD_FORM label"""
    standard_body = " ".join(["word"] * 1000)  # 1000 words
    proposal = create_test_proposal(
        title="Standard Proposal",
        body=standard_body,
        word_count=1000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "LEN-003" in result.reasons
    assert "STANDARD_FORM" in result.labels


# ============================================================================
# TEST: CONFLICT RESOLUTION
# ============================================================================

def test_conflict_multiple_minimums_max_wins(engine):
    """Test that when multiple rules set min_priority, highest wins"""
    # This proposal should trigger both TECH-011 (min 75) and GOV-031 (min 75)
    proposal = create_test_proposal(
        title="Quorum Parameter Update",
        body="Adjusting quorum threshold and parameter config for voting procedure.",
        affects_protocol_parameters=True
    )
    
    result = engine.evaluate_proposal(proposal)
    
    # Both rules should fire
    assert "TECH-011" in result.reasons
    assert "GOV-031" in result.reasons
    
    # Min should be 75 (both set same min)
    assert result.explain["min_priority"] == 75


def test_conflict_caps_win_over_additions(engine):
    """Test that max_priority caps win even if score would be higher"""
    # OPS proposal is capped at 40 regardless of other modifiers
    proposal = create_test_proposal(
        title="Emergency Operational Maintenance",
        body="Critical housekeeping admin with emergency procedures.",
        proposal_kind="ops",
        status="active"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert "OPS-050" in result.reasons
    # Even with emergency keywords, ops cap should win
    assert result.priority_score <= 40


# ============================================================================
# TEST: OVERRIDE SYSTEM
# ============================================================================

def test_override_security_always_urgent(engine):
    """Test that SECURITY label always forces urgent_deep_review"""
    # Even if score is lower, SECURITY → urgent
    proposal = create_test_proposal(
        title="Minor Security Patch",
        body="Small security fix with vulnerability mention.",
        status="closed"  # Closed would normally cap score
    )
    
    result = engine.evaluate_proposal(proposal)
    
    if "SECURITY" in result.labels:
        assert result.recommended_handling == "urgent_deep_review"


# ============================================================================
# TEST: SCORE MAPPING
# ============================================================================

def test_score_mapping_urgent_deep_review(engine):
    """Test score 90-100 → urgent_deep_review"""
    proposal = create_test_proposal(
        title="Critical Emergency Hack Attack",
        body="Severe exploit vulnerability discovered requiring immediate emergency action."
    )
    
    result = engine.evaluate_proposal(proposal)
    
    if result.priority_score >= 90:
        assert result.recommended_handling == "urgent_deep_review"


def test_score_mapping_deep_review(engine):
    """Test score 75-89 → deep_review"""
    proposal = create_test_proposal(
        title="Major Treasury Allocation",
        body="Significant funding request.",
        requested_amount_usd=2_000_000
    )
    
    result = engine.evaluate_proposal(proposal)
    
    if 75 <= result.priority_score < 90:
        assert result.recommended_handling == "deep_review"


def test_score_mapping_fast_track_ok(engine):
    """Test score 25-49 → fast_track_ok"""
    proposal = create_test_proposal(
        title="Minor Update",
        body="Small routine change.",
        proposal_kind="ops"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    if 25 <= result.priority_score < 50:
        assert result.recommended_handling == "fast_track_ok"


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
    assert result.priority_score <= 100


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
    proposal = ProposalInput(
        item_id="null_test",
        title="Minimal Proposal",
        body="Content",
        author="unknown",
        created_at=int(datetime.now(timezone.utc).timestamp()),
        start_at=int(datetime.now(timezone.utc).timestamp()),
        end_at=int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp()),
        status="active",
        # All optional fields left as default None
    )
    
    result = engine.evaluate_proposal(proposal)
    
    assert result is not None
    assert 0 <= result.priority_score <= 100


def test_multiple_labels_accumulate(engine):
    """Test that multiple rules add labels additively"""
    proposal = create_test_proposal(
        title="Treasury Budget for Council Election",
        body="Allocating funding for delegate council nomination process.",
        requested_amount_usd=100_000,
        proposal_kind="election"
    )
    
    result = engine.evaluate_proposal(proposal)
    
    # Should have labels from multiple rules
    assert "TREASURY" in result.labels  # From TRE-020
    assert "ELECTIONS" in result.labels  # From ELE-040
    assert len(result.labels) >= 2  # At least these two


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
