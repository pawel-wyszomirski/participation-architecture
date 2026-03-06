#!/usr/bin/env python3
"""
Governance Alert Bot - Participation Architecture API
=====================================================

Demo script for Video Tutorial 2: "Integrate into a Notification Workflow"

Polls the API for:
  - Delegate Fatigue Index reaching CRITICAL
  - Urgent proposals (priority >= 90, handling = urgent_deep_review)

Usage:
  # Make sure the API is running first:
  # python3 -m uvicorn app.main:app --port 8000
  python3 scripts/governance_alerts.py

Requirements:
  pip install requests
"""

import sys
import requests

BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Step 1: Check fatigue context
# ---------------------------------------------------------------------------

def get_fatigue():
    """Fetch the Delegate Fatigue Index."""
    resp = requests.get(f"{BASE_URL}/delegates/0x0/fatigue")
    resp.raise_for_status()
    return resp.json()


def format_fatigue_alert(dfi):
    """Format an alert if fatigue is CRITICAL."""
    if dfi["status"] == "CRITICAL":
        return (
            f"GOVERNANCE OVERLOAD\n"
            f"DFI = {dfi['fatigue_score']:.0f}/100\n"
            f"Active: {dfi['metrics']['concurrent_active']} proposals\n"
            f"This week: {dfi['metrics']['proposals_7d']} proposals"
        )
    return None


# ---------------------------------------------------------------------------
# Step 2: Check for urgent proposals
# ---------------------------------------------------------------------------

def get_urgent_proposals():
    """Fetch proposals with priority >= 90 and urgent handling."""
    resp = requests.get(f"{BASE_URL}/proposals/feed", params={
        "min_priority": 90,
        "handling": "urgent_deep_review",
        "status": "active",
        "limit": 10,
    })
    resp.raise_for_status()
    return resp.json()["proposals"]


# ---------------------------------------------------------------------------
# Step 3: The main check
# ---------------------------------------------------------------------------

def run_check():
    """Run a single check cycle: fatigue + urgent proposals."""
    alerts = []

    # Check fatigue first - global context
    dfi = get_fatigue()
    print(f"Fatigue: {dfi['fatigue_score']:.0f}/100 ({dfi['status']})")

    alert = format_fatigue_alert(dfi)
    if alert:
        alerts.append(alert)

    # Check for urgent proposals
    urgent = get_urgent_proposals()
    print(f"Urgent proposals found: {len(urgent)}")

    for proposal in urgent:
        alerts.append(
            f"URGENT: {proposal['title'][:80]}\n"
            f"Score: {proposal['priority_score']}, "
            f"Rules: {', '.join(proposal['reasons'])}"
        )

    # Output alerts
    if alerts:
        print(f"\n{'='*50}")
        print(f"{len(alerts)} ALERT(S)")
        print(f"{'='*50}")
        for i, alert in enumerate(alerts, 1):
            print(f"\n[{i}] {alert}")
        print()
        # Replace print() with your delivery method:
        # send_telegram(alert)
        # send_discord_webhook(alert)
        # send_email(alert)
    else:
        print("\nAll quiet - no alerts to send.")


# ---------------------------------------------------------------------------
# Bonus: Quick feed overview
# ---------------------------------------------------------------------------

def show_feed_overview():
    """Show top proposals by priority - useful context."""
    resp = requests.get(f"{BASE_URL}/proposals/feed", params={
        "min_priority": 85,
        "status": "active",
        "limit": 5,
    })
    resp.raise_for_status()
    feed = resp.json()

    print(f"\n--- Top proposals (priority >= 85) ---")
    for p in feed["proposals"]:
        print(
            f"  [{p['priority_score']}] {p['recommended_handling']:22} "
            f"{p['title'][:60]}"
        )
        print(f"       {', '.join(p['labels'])}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Governance Alert Bot - Participation Architecture")
    print("=" * 50)

    try:
        run_check()
        show_feed_overview()
    except requests.ConnectionError:
        print(f"\nERROR: Could not connect to {BASE_URL}")
        print("Make sure the API is running:")
        print("  python3 -m uvicorn app.main:app --port 8000")
        sys.exit(1)
