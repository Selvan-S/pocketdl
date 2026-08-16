# PocketDL 0.1.2 Upgrade

This release is based on PocketDL 0.1.1 and adds the downloader foundation for difficult HLS sources.

## Changes

- Adds `RequestContext` with referer, origin, user-agent and non-sensitive headers.
- Adds `none`, `auto` and `chrome` impersonation modes.
- In `auto`, retries HLS/m3u8 downloads once with Chrome impersonation after an HTTP 403.
- Adds FFmpeg fallback when yt-dlp reports that the native downloader cannot handle a live HLS stream.
- Adds structured error categories while keeping complete yt-dlp output.
- Persists retry count and request-context metadata.
- Adds automatic SQLite migrations for the new fields.
- Declares `yt-dlp[default,curl-cffi]` in both `pyproject.toml` and `requirements.txt`.
- Keeps Cookie/Authorization headers disabled until browser-session capture is designed and secured.

## Upgrade steps on Windows

1. Stop the current frontend and backend.
2. Back up your current project folder.
3. Replace the source files with the 0.1.2 project.
4. Do not copy the old `.venv` directory.
5. From `services/api`, activate a fresh `.venv` and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

6. Verify:

```powershell
python -m yt_dlp --version
python -m yt_dlp --list-impersonate-targets
ffmpeg -version
```

7. Start the backend:

```powershell
python -m app.main
```

8. Start the frontend in another terminal:

```powershell
cd ..\..\apps\web
npm install
npm run dev
```

Your existing SQLite database can remain in place. The backend applies the new columns automatically on startup.
