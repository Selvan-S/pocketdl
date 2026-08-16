# Upgrade to 0.1.3

1. Back up the working 0.1.2 project.
2. Replace the source with the 0.1.3 source package, or apply the patch.
3. Keep your existing SQLite database; no destructive migration is required by this release.
4. Recreate the backend `.venv` only if you prefer a clean environment, then run `pip install -r requirements.txt`.
5. In `apps/web`, run `npm install` and `npm run dev`.
6. Start the backend with `python -m app.main`.

The first new UI action to test is **Analyze**. For difficult HLS URLs, fill the Advanced request options with the same page URL, Referer, Origin and User-Agent observed in the browser and use Auto or Chrome impersonation.
