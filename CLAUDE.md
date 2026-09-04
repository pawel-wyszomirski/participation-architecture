# Participation Architecture

## Opis
Governance Data Pipeline dla DAO (Arbitrum). Deterministyczny triage propozycji głosowań
+ Delegate Fatigue Index (DFI) - mierzenie obciążenia poznawczego delegatów.
Projekt związany z grantem PA ($6,500 / $14,000). FastAPI + SQLAlchemy + PostgreSQL.

## Kluczowe pliki
- `app/main.py` - FastAPI aplikacja v0.7.0 (endpointy: proposals feed, fatigue index)
- `app/services/rule_engine.py` - deterministyczny silnik reguł (triage propozycji)
- `app/services/fatigue_engine.py` - DFI: 5 komponentów (volume, concurrency, burstiness, reading_time, novelty) + `compute_per_event` (per-event, dissertation 5.3.5a). **Od 2026-08-28 (config 1.1.0, punkty 3-4 recenzji /t/30604 wpis 18)**: per-event concurrency liczy OBCIĄŻENIE EKOSYSTEMU (parametr `ecosystem_proposals` - wszystkie propozycje przestrzeni otwarte w t; `fetch_proposals_active_at`), ujawnione zaangażowanie osobno (`voted_concurrent`), źródło nazwane (`concurrency_source`: ecosystem:snapshot | voted_only; None ≠ pusta lista); każdy wynik niesie `MeasurementIdentity` (vote_event_id ze stage_ids scalonego zdarzenia + wersja + commit + source_state z oknami nieznanymi), utrwalane w `fatigue_snapshots` (alembic 002). Odniesienie `concurrent` per-event: 2 (p75 rozkładu ekosystemu), ZAMROŻONE na rundę N=50 (rejestr pomiarów w pa/)
  **Od 2026-09-04 (config 1.2.0, Cross-Layer Closure Review /t/30604 z 03.09, sześć punktów)**: etap decyzji = ZAMROŻONA obserwacja (`merge_stages` nic nie mutuje; cykl przez `lifecycle_id`/`lifecycle_stage_ids`/`stage_index`, zliczanie volume/burstiness po cyklach w `_decision_representatives`); novelty bez samowliczania celu; `SourceReceipt` z każdego źródła + kwalifikowalność fail-closed (`PRIMARY_ELIGIBLE` / `NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS`, reguły `fatigue_config.yaml#eligibility`, fallback `voted_only` dyskwalifikuje); tożsamość natywna (`source_vote_id`, `native_proposal_id`, `voter`, `cast_at`) od ingestu, klienci NIE deduplikują - `reconcile_observations` robi to jawnie; pełny manifest (`MeasurementIdentity.manifest()`, `measurement_id` = skrót całości); brak/zły `fatigue_config.yaml` → `InstrumentInvalid`, endpoint 503 `INSTRUMENT_INVALID` (wag domyślnych NIE MA)
- `app/services/snapshot_client.py` - głosy off-chain (Snapshot GraphQL); `fetch_voted_observations` → (lista, `SourceReceipt`), `fetch_voted_proposals` = wrapper bez pokwitowania; `fetch_ecosystem_exposure` → (lista|None, pokwitowanie). Endpoint pyta o 1000 (sufit strony); TRUNCATED ocenia silnik względem `eligibility.context_window_days` po `oldest_cast_at`
- `app/services/arbdata_client.py` - rejestr taksonomii DAO (kategorie dla `novelty`, okna głosowań Governora). **Źródło wymagane z pokwitowaniem `taxonomy`** (od 2026-09-04: endpoint odpowiada 403, wcześniej `load()` milczało i novelty spadało na listę słów przy czystym werdykcie). Udany odczyt zapisuje `data/cache/arbdata-registry.json`; przy awarii kopia wchodzi jako PARTIAL z datą, bez kopii = ERROR = NOT_ELIGIBLE
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
- `GET /delegates/{address}/per-event-fatigue` - per-event DFI dla JEDNEGO głosu-etapu (najnowszy lub `?proposal_id=` = id etapu: Snapshot, `tally:<id>`, `governor:<core|treasury>:<id>`); trzy źródła + ekspozycja ekosystemu, as_of=czas głosu. **TYLKO ODCZYT - nie zapisuje wiersza** (od 2026-09-04)
- `POST /delegates/{address}/per-event-fatigue` - to samo obliczenie + rejestracja w `fatigue_snapshots` idempotentnie po `measurement_id` (UNIQUE, alembic 003); odpowiedź `persisted: true|false`. `pa/analiza/prep-dataset.py` woła POST
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
- Oba mogą nie zainicjować się (brak YAML) - API zwraca 503. FatigueEngine od 2026-09-04 NIE MA wag domyślnych: brak pliku, zły YAML, brakujący klucz albo wagi ≠ 1,0 = `InstrumentInvalid` (503 `INSTRUMENT_INVALID`), celowo - instrument zamrożony na N=50 nie może liczyć „czegoś innego, co nadal nazywa się DFI"
- Testy odpalaj z katalogu repo (`python3 -m pytest -q`): silnik czyta `fatigue_config.yaml` ze ścieżki względnej; `tests/test_api_per_event.py` ustawia `DATABASE_URL` na tymczasowy SQLite PRZED importem `app.main` i podmienia klientów źródeł atrapami
- DFI jest ecosystem-level (wspólny dla wszystkich delegatów), address to forward-compatible placeholder
- Wagi DFI: volume 40%, concurrency 25%, burstiness 20%, reading_time 10%, novelty 5%
- `participation.db` (SQLite) obok Docker PostgreSQL - uważaj na spójność
- Projekt akademicki (dissertation) - kod z teoretycznym uzasadnieniem (Fogg B=MAP, CLT)
