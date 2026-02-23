# Video Tutorial 1: Quickstart

**"Clone, run, first API call in 5 minutes"**

Target audience: Developers who want to run the API locally for the first time.
Duration: ~5-7 minutes.

---

## Script

### Intro (0:00 - 0:30)

> "Hi, I'm Pawel. This is the Participation Architecture API - governance middleware for Arbitrum DAO. In this video, I'll show you how to go from zero to your first API call in about 5 minutes."

> "The API gives you two things: a deterministic triage feed for governance proposals - each proposal gets a priority score and labels telling you what kind of review it needs - and a Delegate Fatigue Index, which measures how much cognitive load the current governance activity is putting on delegates."

> "Let's get started."

---

### Step 1: Clone and install (0:30 - 1:30)

**Show terminal:**

```bash
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
pip install -r requirements.txt
```

> "First, clone the repo and install dependencies. You'll need Python 3.11 or later. No external API keys required - the governance data comes from Snapshot.org, which is public."

> "Requirements include FastAPI, SQLAlchemy, and PyYAML - lightweight, no ML dependencies. The rule engine is fully deterministic."

---

### Step 2: Ingest data (1:30 - 2:30)

```bash
python3 app/services/snapshot_client.py
```

> "Now let's fetch the governance data. This script downloads Arbitrum DAO proposals from Snapshot.org and stores them in a local SQLite database."

> "You should see about 400 proposals ingested. These are real Arbitrum DAO governance proposals going back several years."

---

### Step 3: Start the API (2:30 - 3:00)

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> "Start the API server. You'll see the startup banner showing the rule engine version and fatigue engine version. The --reload flag means it will auto-restart when you change files."

---

### Step 4: First API calls (3:00 - 5:00)

**Open a second terminal:**

```bash
curl http://localhost:8000/health
```

> "Health check first. You can see the database is connected, 399 proposals loaded, and both engines are initialized."

```bash
curl "http://localhost:8000/proposals/feed?min_priority=80&limit=5" | python3 -m json.tool
```

> "Now the most important endpoint - the proposals feed. I'm filtering for proposals with a priority score of 80 or higher."

> "Each proposal has a `priority_score`, `labels` like PROTOCOL_UPGRADE or TREASURY_TIER_1, `reasons` which are the rule IDs that fired, and `recommended_handling` telling you what kind of attention this needs."

> "This is fully deterministic. No AI, no randomness. Same proposal always gets the same score."

```bash
curl "http://localhost:8000/delegates/0x1234/fatigue" | python3 -m json.tool
```

> "And the Delegate Fatigue Index. This tells you the overall governance workload right now. The formula is right there in the response - fully transparent, no black box."

---

### Step 5: Swagger UI (5:00 - 6:00)

**Open browser, navigate to http://localhost:8000/docs**

> "FastAPI gives us an interactive Swagger UI out of the box. Every endpoint is documented here, you can try requests directly in the browser."

---

### Wrap up (6:00 - 7:00)

> "That's the quickstart. You have a running API with 400 real governance proposals, a triage feed, and a fatigue index."

> "In the next videos I'll show you how to integrate this into a notification bot and how to customize the rulebook to add your own triage rules."

> "The repo is at github.com/pawel-wyszomirski/participation-architecture. Full documentation is in the docs/ folder. Thanks!"

---

## Demo commands summary

```bash
# Terminal 1 - API server
git clone https://github.com/pawel-wyszomirski/participation-architecture.git
cd participation-architecture
pip install -r requirements.txt
python3 app/services/snapshot_client.py
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - API calls
curl http://localhost:8000/health | python3 -m json.tool
curl "http://localhost:8000/proposals/feed?min_priority=80&limit=5" | python3 -m json.tool
curl "http://localhost:8000/delegates/0x1234/fatigue" | python3 -m json.tool
```
