# Participation Architecture

## Opis
Governance Data Pipeline dla DAO (Arbitrum). Deterministyczny triage propozycji głosowań
+ Delegate Fatigue Index (DFI) - mierzenie obciążenia poznawczego delegatów.
Projekt związany z grantem PA ($6,500 / $14,000). FastAPI + SQLAlchemy + PostgreSQL.

## Kluczowe pliki
- `app/main.py` - FastAPI aplikacja v0.7.0 (endpointy: proposals feed, fatigue index)
- `app/services/rule_engine.py` - deterministyczny silnik reguł (triage propozycji)
- `app/services/fatigue_engine.py` - DFI: 5 komponentów (volume, concurrency, burstiness, reading_time, novelty) + `compute_per_event` (per-event, dissertation 5.3.5a)
- `app/services/snapshot_client.py` - głosy off-chain (Snapshot GraphQL); `fetch_voted_proposals` zwraca `voted_at`+`source`
- `app/services/tally_client.py` - głosy ON-CHAIN (Tally); 2-step (proposals Arbitrum org `2206072050315953936` → votes by proposalIds+voter, bo Tally nie ma votes-by-voter). Klucz: env `TALLY_API_KEY`
- `app/static/dashboard.html` - DFI dashboard (vanilla JS, serwowany przez `GET /`); per-event UI dla doktoratu, branch `feature/dfi-per-delegate-research`
- `app/db/models.py` - modele SQLAlchemy (Proposal, FatigueSnapshot, Vote)
- `rulebook.yaml` - konfiguracja reguł triagu
- `fatigue_config.yaml` - wagi i progi DFI
- `docker-compose.yml` - PostgreSQL 15 + API (dev)
- `src/cli.py` - CLI do zarządzania
- `alembic/` - migracje bazy danych
- `tests/` - testy pytest

## Endpointy API
- `GET /` - DFI dashboard (HTML, `?address=`); na produkcji `arbitrum.wyszomirski.online` (osobny kontener, branch feature/dfi-per-delegate-research)
- `GET /delegates/{address}/per-event-fatigue` - per-event DFI dla JEDNEGO głosu (najnowszy lub `?proposal_id=`); scala on-chain (Tally) + off-chain (Snapshot), as_of=czas głosu
- `GET /proposals/feed` - lista propozycji z priorytetem (filtry: min_priority, label, handling, status)
- `GET /proposals/{id}` - szczegóły z audit trail
- `GET /delegates/{address}/fatigue` - DFI score (0-100) ecosystem-level (grant) z rozbiciem na komponenty
- `GET /delegates/{address}/fatigue/history` - historia DFI
- `GET /health` - healthcheck
- `GET /debug/*` - debug endpointy (rulebook, fatigue-config, raw proposals)

## Konfiguracja
- Docker: `docker-compose up` (PostgreSQL + API)
- DB: `postgresql+asyncpg://user:password@db:5432/participation_arch`
- Baza lokalna: `participation.db` (SQLite do dev?)
- Alembic: migracje w `alembic/`

## Zależności
- fastapi, uvicorn, sqlalchemy, alembic, pydantic, httpx, openai
- PostgreSQL 15 (Docker)

## Pułapki
- Dwa silniki niezależne: RuleEngine (rulebook.yaml) i FatigueEngine (fatigue_config.yaml)
- Oba mogą nie zainicjować się (brak YAML) - API zwraca 503
- DFI jest ecosystem-level (wspólny dla wszystkich delegatów), address to forward-compatible placeholder
- Wagi DFI: volume 40%, concurrency 25%, burstiness 20%, reading_time 10%, novelty 5%
- `participation.db` (SQLite) obok Docker PostgreSQL - uważaj na spójność
- Projekt akademicki (dissertation) - kod z teoretycznym uzasadnieniem (Fogg B=MAP, CLT)
