# Upgrade to PocketDL 0.2.0

## Recommended migration

1. Stop the v0.1.x backend and frontend.
2. Back up your existing project directory.
3. Replace the source with the v0.2.0 project.
4. Keep the existing SQLite database. v0.2 adds columns/tables non-destructively.
5. Create a fresh backend virtual environment if you prefer a clean install, then run `pip install -r requirements.txt`.
6. Run `npm install` from the repository root.
7. Run the backend and frontend using the commands in README.md.
8. Build and load the PocketDL Capture extension.

## Database

No manual database recreation is required. The download repository adds the `source_type` column when a v0.1 database is detected. The capture repository creates the `captures` table on startup.

## First v0.2 test

Use Chrome and a page where the browser successfully requests an HLS `.m3u8` manifest. Confirm that it appears under **Browser captures** and then queue it for download.
