# PocketDL — Development and Git Workflow

## Canonical source
GitHub should be the source of truth once v0.2.2 is pushed.

Repository:

`git@github_personal:Selvan-S/pocketdl.git`

Use the existing local GitHub SSH host alias configured by the developer.

## First GitHub push checklist

From the repository root:

```powershell
# Verify branch/remotes
 git status
 git remote -v
 git branch
```

Inspect ignored files:

```powershell
git status --ignored
```

Inspect staged file list:

```powershell
git diff --cached --name-only
```

Important: source files must not be ignored. In particular, verify:

```text
services/api/app/application/downloads/service.py
services/api/app/application/downloads/strategy.py
services/api/app/application/downloads/errors.py
services/api/app/application/captures/service.py
```

Generated/runtime material should be ignored:

```text
**/.venv/
**/node_modules/
**/__pycache__/
**/.pytest_cache/
**/dist/
*.db
*.sqlite
*.sqlite3
*.log
.env
.env.*
```

## Updating after a new version
Do not delete or recreate `.git`.

Preferred workflow:

```text
feature branch
   ↓
implement + test
   ↓
commit
   ↓
push
   ↓
merge to main
   ↓
tag/release
```

For a small fix:

```powershell
git checkout -b fix/<short-name>
```

For a feature:

```powershell
git checkout -b feature/<short-name>
```

## Versioning
Use semantic-ish product versions:

- `0.2.x` = browser capture/mobile stabilization.
- `0.3.x` = richer analysis/format selection.
- `0.4.x` = Android/Termux productization.
- `1.0.0` = stable public milestone.

## Commit style
Prefer Conventional Commit style:

```text
feat: add captured media metadata
fix: deduplicate refreshed HLS manifests
refactor: separate capture application service
chore: update dependencies
 test: cover duplicate capture identity
 docs: document Termux setup
```

## Regression rule
Every discovered bug should produce a regression test where technically practical.

Examples:
- duplicate capture identity test.
- SQLite migration test.
- filename sanitization test.
- download error classification test.
- request-context validation test.
- captured HLS strategy test.

## Release checklist
Before tagging a version:

```text
[ ] Backend tests pass
[ ] Extension typecheck passes
[ ] Extension build passes
[ ] Frontend typecheck/build passes where dependencies are available
[ ] No secrets in repository
[ ] No runtime DB/logs/node_modules/.venv/dist/__pycache__ committed
[ ] Migration path tested
[ ] README updated
[ ] CHANGELOG updated
[ ] Upgrade notes added for breaking/config changes
[ ] Manual smoke test completed
```

## Desktop commands

Backend:

```powershell
cd services\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # includes requirements.txt; use requirements.txt alone for runtime only
python -m app.main
```

Frontend:

```powershell
cd apps\web
npm ci
npm run dev
```

Extension:

```powershell
npm ci
npm run extension:build
```

## Android commands

Use the installer rather than running these steps by hand; it is the single
maintained definition of the Android setup:

```bash
cd ~/pocketdl
bash scripts/termux-install.sh
bash scripts/termux-doctor.sh --all
pocketdl
```

The equivalent manual steps, for debugging a failed install:

```bash
# M1 runtime
pkg update && pkg upgrade
termux-setup-storage
pkg install git python nodejs-lts ffmpeg aria2

# Build toolchain — Termux is Bionic, so these dependencies compile from source
pkg install clang make binutils pkg-config rust libffi openssl

# Backend
cd ~/pocketdl/services/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # add -r requirements-dev.txt to run tests
python -m app.main
```

Frontend development server:

```bash
cd ~/pocketdl
npm ci
npm run web:dev -- --host 127.0.0.1
```

Note that `npm run web:build` must succeed for the backend to serve the PWA at
`/`; without `apps/web/dist` only the API and Swagger respond.

## Important Android lesson
If a Python import works on Windows but fails after cloning on Android, check Git tracking before changing Python code. A prior `.gitignore` incident omitted a real source file from the checkout.
