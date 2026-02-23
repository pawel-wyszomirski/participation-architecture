# Video Tutorial 2: Integrate into a Notification Workflow

**"Build a governance alert bot in 15 minutes"**

Target audience: Developers building governance dashboards, bots, or alert systems.
Duration: ~12-15 minutes.

---

## What we'll build

A Python script that:
1. Polls the API every hour
2. Sends alerts when urgent proposals appear or fatigue reaches CRITICAL
3. Shows the pattern you'd replicate in a Telegram bot, Discord webhook, or cron job

---

## Script

### Intro (0:00 - 0:45)

> "In this video, I'll show you how to integrate the Participation Architecture API into a notification workflow. We'll build a polling script that checks for urgent proposals and governance overload."

> "Prerequisites: the API is running locally from tutorial 1. Let's go."

---

### Step 1: Check fatigue context (2:00 - 4:00)

```python
def get_fatigue():
    resp = requests.get(f"{BASE_URL}/delegates/0x0/fatigue")
    resp.raise_for_status()
    return resp.json()

def format_fatigue_alert(dfi):
    if dfi["status"] == "CRITICAL":
        return (
            f"GOVERNANCE OVERLOAD\n"
            f"DFI = {dfi['fatigue_score']:.0f}/100\n"
            f"Active: {dfi['metrics']['concurrent_active']} proposals\n"
            f"This week: {dfi['metrics']['proposals_7d']} proposals"
        )
    return None
```

> "Check fatigue first - if CRITICAL, send an alert regardless of individual proposals."

---

### Step 2: Check for urgent proposals (4:00 - 6:00)

```python
def get_urgent_proposals():
    resp = requests.get(f"{BASE_URL}/proposals/feed", params={
        "min_priority": 90,
        "handling": "urgent_deep_review",
        "status": "active",
        "limit": 10,
    })
    resp.raise_for_status()
    return resp.json()["proposals"]
```

> "Filter by min_priority=90 and handling=urgent_deep_review. These need immediate attention."

---

### Step 3: The main loop (7:30 - 10:00)

```python
def run_check():
    alerts = []

    dfi = get_fatigue()
    alert = format_fatigue_alert(dfi)
    if alert:
        alerts.append(alert)

    for proposal in get_urgent_proposals():
        alerts.append(
            f"URGENT: {proposal['title'][:80]}\n"
            f"Score: {proposal['priority_score']}, Rules: {', '.join(proposal['reasons'])}"
        )

    if alerts:
        for alert in alerts:
            print(alert)
            # Replace with: send_telegram(alert) / send_discord_webhook(alert)
    else:
        print("All quiet - no alerts to send.")

if __name__ == "__main__":
    run_check()
```

---

### Adding a schedule (11:30 - 13:00)

**Option 1: cron**
```bash
0 * * * * python3 /path/to/scripts/governance_alerts.py >> /var/log/governance_alerts.log 2>&1
```

**Option 2: GitHub Actions**
```yaml
name: Governance Alerts
on:
  schedule:
    - cron: "0 * * * *"
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install requests
      - run: python3 scripts/governance_alerts.py
```

---

### Wrap up

> "The key insight: check fatigue first for global context, then look at labeled proposals for specific actions."

> "The API is stateless and deterministic - same governance state always produces the same scores."

> "The full script is in docs/examples/python_example.py."

---

## Demo commands summary

```python
import requests

BASE_URL = "http://localhost:8000"

dfi = requests.get(f"{BASE_URL}/delegates/0x0/fatigue").json()
print(f"Fatigue: {dfi['fatigue_score']:.0f} ({dfi['status']})")

feed = requests.get(f"{BASE_URL}/proposals/feed", params={
    "min_priority": 85,
    "status": "active",
    "limit": 5,
}).json()

for p in feed["proposals"]:
    print(f"[{p['priority_score']}] {p['recommended_handling']:22} {p['title'][:60]}")
    print(f"       {', '.join(p['labels'])}")
```
