# Video Tutorial 2: Integrate into a Notification Workflow

**"Build a governance alert bot in 15 minutes"**

Target audience: Developers building governance dashboards, bots, or alert systems.
Duration: ~12-15 minutes.

Prerequisites: API running locally (see Tutorial 1).

---

## What we'll build

A Python script that:
1. Checks the Delegate Fatigue Index for governance overload
2. Scans for urgent proposals (priority >= 90)
3. Outputs alerts you'd send to Telegram, Discord, or email

The complete, runnable script is already in the repo at `scripts/governance_alerts.py`.
A more comprehensive integration example is at `docs/examples/python_example.py`.

---

## Script

### Intro (0:00 - 0:45)

> "In this video, I'll show you how to integrate the Participation Architecture API into a notification workflow. We'll walk through a governance alert bot that checks for urgent proposals and governance overload."

> "The complete script is already in the repo - you can run it right away. But let's walk through how it works."

---

### Step 1: Run the alert bot (0:45 - 2:00)

**Show terminal (API must be running from Tutorial 1):**

```bash
python3 scripts/governance_alerts.py
```

> "Let's run it first to see what it does, then walk through the code."

> "You can see it checks the fatigue index first - that's the global governance load - then scans for urgent proposals. If anything needs attention, it outputs alerts."

---

### Step 2: Walk through the code (2:00 - 6:00)

**Open `scripts/governance_alerts.py` in editor:**

> "The script has three key functions. Let's look at each."

**Fatigue check:**

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

> "Check fatigue first. If the status is CRITICAL, we send an alert regardless of individual proposals. This gives you global context before diving into specifics."

**Urgent proposals:**

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

> "Filter by min_priority=90 and handling=urgent_deep_review. These are proposals that need immediate attention."

**Main check loop:**

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
            f"Score: {proposal['priority_score']}, "
            f"Rules: {', '.join(proposal['reasons'])}"
        )

    if alerts:
        for alert in alerts:
            print(alert)
            # Replace with: send_telegram(alert) / send_discord_webhook(alert)
    else:
        print("All quiet - no alerts to send.")
```

> "Collect all alerts, then deliver them. Right now it just prints - replace the print with your delivery method: Telegram, Discord, email, whatever you use."

---

### Step 3: Run the full example (6:00 - 8:00)

```bash
python3 docs/examples/python_example.py
```

> "There's also a more comprehensive example that shows all API features: health check, filtered feeds, proposal details, fatigue breakdown with component visualization, and status-based action routing."

---

### Step 4: Scheduling (8:00 - 10:00)

> "To make this run automatically, you have two options."

**Option 1: cron (simplest)**
```bash
# Check every hour
0 * * * * cd /path/to/participation-architecture && venv/bin/python3 scripts/governance_alerts.py >> /var/log/governance_alerts.log 2>&1
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
        env:
          API_URL: https://your-deployment-url.example.com
```

---

### Wrap up (10:00 - 11:00)

> "The key pattern: check fatigue first for global context, then look at specific proposals."

> "The API is stateless and deterministic - same governance state always produces the same scores. No surprises."

> "Both scripts are in the repo ready to use: `scripts/governance_alerts.py` for quick alerts, `docs/examples/python_example.py` for a full integration demo. In the next video, we'll customize the rulebook."

---

## Demo commands summary

```bash
# Run the alert bot
python3 scripts/governance_alerts.py

# Run the full integration example
python3 docs/examples/python_example.py

# Interactive exploration
python3
>>> import requests
>>> r = requests.get("http://localhost:8000/delegates/0x0/fatigue")
>>> r.json()["status"]
'MODERATE'
>>> r.json()["fatigue_score"]
42.5
```
