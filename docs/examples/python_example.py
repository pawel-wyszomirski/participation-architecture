"""
Python Integration Example - Participation Architecture API
===========================================================

Demonstrates common integration patterns:
  - Health check
  - High-priority proposals feed
  - Single proposal with full audit trail
  - Delegate Fatigue Index with component breakdown
  - Status-based action routing

Requirements:
  pip install requests

Usage:
  # Make sure the API is running first:
  # python3 -m uvicorn app.main:app --port 8000
  python3 docs/examples/python_example.py
"""

import sys
import requests
from datetime import datetime

BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# API client helpers
# ---------------------------------------------------------------------------

def get(path: str, params: dict = None) -> dict:
    """Simple GET wrapper with error handling."""
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------

def example_health_check():
    """Check API health and verify both engines are initialized."""
    print("\n--- Health Check ---")
    health = get("/health")

    print(f"  Status:           {health['status']}")
    print(f"  API version:      {health['version']}")
    print(f"  Database:         {health['database']}")
    print(f"  Proposals in DB:  {health['proposals_count']}")
    print(f"  Rule Engine:      {health['rule_engine']} (rulebook v{health['rulebook_version']})")
    print(f"  Fatigue Engine:   {health['fatigue_engine']} (config v{health['fatigue_config_version']})")

    if health["rule_engine"] != "initialized":
        print("  WARNING: Rule engine not initialized. Check rulebook.yaml exists.")
    if health["fatigue_engine"] != "initialized":
        print("  WARNING: Fatigue engine not initialized. Check fatigue_config.yaml exists.")

    return health


def example_proposals_feed(min_priority: int = 80, label: str = None):
    """Fetch proposals filtered by priority score and/or label."""
    params = {"min_priority": min_priority, "limit": 20}
    if label:
        params["label"] = label

    description = f"min_priority={min_priority}"
    if label:
        description += f", label={label}"

    print(f"\n--- Proposals Feed ({description}) ---")
    data = get("/proposals/feed", params=params)

    print(f"  Total in DB:       {data['total']}")
    print(f"  Returned:          {len(data['proposals'])}")
    print(f"  Has next page:     {data['has_next']}")
    print()

    for p in data["proposals"]:
        score = p["priority_score"]
        handling = p["recommended_handling"]
        title = p["title"][:55]
        labels = ", ".join(p["labels"])
        rules = ", ".join(p["reasons"])

        print(f"  [{score:3d}] {handling:<22} {title}")
        print(f"         Labels: {labels}")
        print(f"         Rules:  {rules}")
        print()

    return data


def example_proposal_detail(proposal_id: str):
    """Fetch a single proposal with its full rule audit trail."""
    print(f"\n--- Proposal Detail: {proposal_id[:20]}... ---")
    p = get(f"/proposals/{proposal_id}")

    if p is None:
        print(f"  Proposal not found: {proposal_id}")
        return None

    print(f"  Title:     {p['title']}")
    print(f"  Score:     {p['priority_score']}")
    print(f"  Handling:  {p['recommended_handling']}")
    print(f"  Labels:    {', '.join(p['labels'])}")
    print(f"  Rules:     {', '.join(p['reasons'])}")
    print(f"  State:     {p['metadata']['state']}")
    print(f"  Votes:     {p['metadata']['votes']}")

    if "explain" in p and p["explain"]:
        print(f"  Explain:   {p['explain']}")

    return p


def example_delegate_fatigue(address: str = "0x0000000000000000000000000000000000000001"):
    """Fetch ecosystem governance fatigue index with full component breakdown."""
    print(f"\n--- Delegate Fatigue Index ---")
    print(f"  Address:   {address}")

    dfi = get(f"/delegates/{address}/fatigue")

    print(f"  Score:     {dfi['fatigue_score']:.1f} / 100")
    print(f"  Status:    {dfi['status']}")
    print(f"  Formula:   {dfi['formula']}")
    print(f"  Computed:  {dfi['computed_at']}")
    print()

    print("  Components (each 0.0-1.0, weighted contribution):")
    for name, value in dfi["components"].items():
        weight = dfi["weights"][name]
        contribution = value * weight * 100
        bar = "=" * int(value * 20)
        print(f"    {name:<15} {value:.3f}  (w={weight:.2f}, contrib={contribution:.1f})  [{bar:<20}]")

    print()
    print("  Raw metrics:")
    m = dfi["metrics"]
    print(f"    proposals_7d:       {m['proposals_7d']}")
    print(f"    proposals_30d:      {m['proposals_30d']}")
    print(f"    concurrent_active:  {m['concurrent_active']}")
    print(f"    avg_word_count:     {m['avg_word_count']:.0f}")
    print(f"    weekly_avg:         {m['weekly_avg']:.2f}")
    print(f"    novelty_ratio:      {m['novelty_ratio']:.3f}")

    return dfi


def example_status_routing(dfi: dict):
    """Show status-based action routing pattern."""
    print(f"\n--- Status-based Action Routing ---")
    status = dfi["status"]
    score = dfi["fatigue_score"]

    print(f"  DFI = {score:.1f} ({status})")

    actions = {
        "CRITICAL": [
            "Pause non-urgent proposals or batch them",
            "Extend voting windows if possible",
            "Alert delegates: high cognitive load period",
            "Focus exclusively on urgent_deep_review items",
        ],
        "HIGH": [
            "Prioritize triage: process deep_review items first",
            "Defer fast_track items if possible",
            "Monitor for upward trend in proposals_7d",
        ],
        "MODERATE": [
            "Normal operation - all handling modes applicable",
            "Review standard_review items before deadlines",
            "Burstiness spike? Check weekly trend.",
        ],
        "LOW": [
            "Healthy load - process all item types",
            "Good time to fast-track routine operations",
            "Capture any governance debt from previous HIGH periods",
        ],
    }

    print(f"\n  Suggested actions for {status}:")
    for action in actions.get(status, []):
        print(f"    - {action}")

    return status


def example_fatigue_history(address: str = "0x0000000000000000000000000000000000000001", limit: int = 5):
    """Fetch historical DFI snapshots for trend analysis."""
    print(f"\n--- Fatigue History (last {limit} snapshots) ---")
    history = get(f"/delegates/{address}/fatigue/history", params={"limit": limit})

    if not history:
        print("  No history yet. Call the fatigue endpoint a few times first.")
        return

    print(f"  {'Timestamp':<28}  {'Score':>6}  {'Status':<10}  {'30d':>4}  {'Active':>6}")
    print(f"  {'-'*28}  {'-'*6}  {'-'*10}  {'-'*4}  {'-'*6}")
    for row in history:
        ts = row["computed_at"][:19].replace("T", " ")
        print(f"  {ts:<28}  {row['fatigue_score']:>6.1f}  {row['status']:<10}  {row['proposals_30d']:>4}  {row['concurrent_active']:>6}")

    return history


# ---------------------------------------------------------------------------
# Run all examples
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Participation Architecture API - Python Integration Demo")
    print("=" * 60)

    try:
        health = example_health_check()
    except requests.ConnectionError:
        print(f"\nERROR: Could not connect to {BASE_URL}")
        print("Make sure the API is running:")
        print("  python3 -m uvicorn app.main:app --port 8000")
        sys.exit(1)

    example_proposals_feed(min_priority=80)
    example_proposals_feed(min_priority=60, label="PROTOCOL_UPGRADE")

    feed = get("/proposals/feed", params={"limit": 1})
    if feed and feed["proposals"]:
        first_id = feed["proposals"][0]["id"]
        example_proposal_detail(first_id)

    dfi = example_delegate_fatigue()
    example_status_routing(dfi)
    example_fatigue_history()

    print("\n" + "=" * 60)
    print("Done. Open http://localhost:8000/docs for interactive API explorer.")
    print("=" * 60)
