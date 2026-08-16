# Upgrade to PocketDL 0.2.2

1. Keep your existing 0.2.1 project as a backup.
2. Replace it with the 0.2.2 project.
3. Recreate the backend virtual environment and run `pip install -r requirements.txt`.
4. Run `npm install` at the project root.
5. Build/reload the extension with `npm run extension:build`.
6. Start the backend and frontend as usual.

The existing SQLite database is migrated automatically. Historical capture duplicates are normalized during startup and the newest capture is kept.

No FFmpeg reinstall is required when FFmpeg is already available on PATH.
