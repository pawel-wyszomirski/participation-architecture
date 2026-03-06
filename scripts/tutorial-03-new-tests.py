# Tutorial 3: New test cases for PROG-002 rule
# Paste these into tests/rules/test_rule_engine.py
#
# Usage during video recording:
#   cat scripts/tutorial-03-new-tests.py
#   # then copy-paste the functions below into the test file


def test_prog_002_developer_grants(engine):
    """PROG-002: Developer grant keywords -> DEVELOPER_GRANTS label"""
    proposal = create_test_proposal(
        title="Developer Grants Program Q1",
        body="Proposing a new developer incentive and build grant to attract builders."
    )
    result = engine.evaluate_proposal(proposal)

    assert "PROG-002" in result.reasons
    assert "DEVELOPER_GRANTS" in result.labels
    assert result.priority_score >= 65


def test_prog_002_negative(engine):
    """PROG-002: Generic grants without developer context -> Should NOT fire"""
    proposal = create_test_proposal(
        title="Community Grant",
        body="General community funding without developer focus."
    )
    result = engine.evaluate_proposal(proposal)

    assert "PROG-002" not in result.reasons
    assert "DEVELOPER_GRANTS" not in result.labels
