# Development workflow

## Backend

```powershell
cd services\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m app.main
```

`requirements-dev.txt` includes `requirements.txt` and adds the test-only
dependencies (pytest, pytest-asyncio, httpx2). Install `requirements.txt` alone
for a runtime-only environment.

## Frontend

```powershell
cd apps\web
npm ci
npm run dev
```

Use `npm ci` rather than `npm install` so the committed lockfile is respected;
this is what keeps the Windows and Termux dependency trees identical.

## Validation

Backend:

```powershell
cd services\api
python -m compileall -q app tests
pytest -q
```

Frontend:

```powershell
npm run web:build
npm run web:test
```

Extension:

```powershell
npm run extension:typecheck
npm run extension:build
```

`npm run web:build` must pass: the backend mounts `apps/web/dist` to serve the
PWA at `/`, so a failed web build silently degrades the app to API-only.

## Android

See [termux.md](termux.md). `scripts/termux-doctor.sh` is the mechanical
verification for the Android milestones and exits non-zero on M1 failure.

## Dependency note

The backend installs `yt-dlp[default,curl-cffi]`; the curl_cffi extra is
required for the browser-impersonation strategies. Dependency versions are
declared in `requirements.txt` / `pyproject.toml` and the npm lockfile only —
installer scripts must not introduce their own package lists.
