# Deployment

Production runtime for `pa.wyszomirski.online`.

## Topology

| Component | Value |
|---|---|
| Host | `89.167.126.253` (Hetzner Helsinki, alias `produkcja`) |
| Repo path | `/opt/participation-architecture` |
| Container | `pa-api` (image `pa-api:latest`, restart `unless-stopped`) |
| Port | `127.0.0.1:8000` → nginx → `pa.wyszomirski.online` (SSL via Let's Encrypt, expires 2026-06-04) |
| DB | SQLite at `/app/participation.db` inside the container. The file is shipped by `COPY . .` in the Dockerfile, so it lives **inside the image**, not on a bind mount. Rebuild = fresh data from the repo snapshot. |
| Bind mount | `/opt/pa-data` → `/app/data` (auxiliary CSV/cache files only — the SQLite DB does not live here despite the name) |

## Deploy procedure

From the developer machine (mozg):

```bash
# 1. Push changes to GitHub main
git push origin main   # requires UWAZAJ_OFF=1 (block-uwazaj.sh hook)
```

On `produkcja` (89.167.126.253):

```bash
cd /opt/participation-architecture
git pull origin main
docker build -t pa-api .
docker stop pa-api
docker rm pa-api
docker run -d --name pa-api --restart unless-stopped \
    -p 127.0.0.1:8000:8000 \
    -v /opt/pa-data:/app/data \
    pa-api
sleep 4
curl -s http://127.0.0.1:8000/health
```

Health response should include `"status":"ok"` and a non-zero `proposals_count`.

## Public smoke test

```bash
curl -s https://pa.wyszomirski.online/health
curl -s "https://pa.wyszomirski.online/delegates/0xtest/fatigue"
curl -s "https://pa.wyszomirski.online/delegates/0xtest/fatigue?as_of=2025-12-01T00:00:00Z"
```

## Pitfalls

- **`USER appuser` in the Dockerfile** — uvicorn runs as uid 1000. SQLite needs to write a journal/WAL file *next to* the DB, so the entire `/app` directory must be owned by appuser. The Dockerfile chown happens during `useradd`. If you ever rearrange those steps, the container will crash on startup with `attempt to write a readonly database`.
- **The DB file is in the image, not on a volume.** A `docker build` therefore takes whatever `participation.db` exists in the working tree and bakes it into the new image. Old containers keep their internal copy until removed. To preserve runtime writes across deploys, either (a) move the DB to `/app/data` and set `DATABASE_URL=sqlite:////app/data/participation.db`, or (b) `docker cp pa-api:/app/participation.db .` before rebuilding.
- **`git push origin main` is blocked by the user's `block-uwazaj.sh` hook.** Bypass with the `UWAZAJ_OFF=1` prefix only when explicitly authorized.
- **SSH to the production host is also blocked by `block-uwazaj.sh` and by Claude Code's permission system.** Each session needs an explicit user authorization naming the target IP.
