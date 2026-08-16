# Development workflow

## Backend

```powershell
cd services\api
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## Frontend

```powershell
cd apps\web
npm install
npm run dev
```

## Validation

Backend:

```powershell
cd services\api
python -m compileall -q app tests
pytest -q
```

Frontend:

```powershell
cd apps\web
npm run build
npm run test
```

## v0.1.2 dependency note

The backend explicitly installs `yt-dlp[default,curl-cffi]`. This is required for browser impersonation strategies.
