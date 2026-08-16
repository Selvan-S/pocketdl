# Upgrade to PocketDL 0.2.1

1. Keep your existing PocketDL project as a backup.
2. Replace it with the v0.2.1 project.
3. Create a fresh backend `.venv` and run `pip install -r requirements.txt`.
4. Run `npm install` from the project root.
5. Rebuild and reload the browser extension with `npm run extension:build`.
6. Start the backend and web app as before.

The existing SQLite database is migrated in place. The selected download directory is stored in `~/.pocketdl/settings.json` (or the corresponding Termux home directory) and can be changed from the Settings panel.
