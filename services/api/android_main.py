import os
import threading
import uvicorn
from app.main import app

def start_server(storage_dir: str):
    """
    Called by Chaquopy from MainActivity.java to start the FastAPI server.
    storage_dir is passed from Android's context.getExternalFilesDir(null)
    to ensure we have write permissions for SQLite and downloads.
    """
    # Configure environment variables for the app settings
    os.environ['POCKETDL_DATABASE_PATH'] = os.path.join(storage_dir, 'pocketdl.db')
    os.environ['POCKETDL_DOWNLOAD_DIRECTORY'] = os.path.join(storage_dir, 'Downloads')
    
    # Ensure directories exist
    os.makedirs(os.environ['POCKETDL_DOWNLOAD_DIRECTORY'], exist_ok=True)
    
    # Expose bundled FFmpeg executable to yt-dlp
    bin_dir = os.path.join(storage_dir, 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    os.environ['PATH'] = f"{bin_dir}:{os.environ.get('PATH', '')}"
    
    def run():
        # Run uvicorn on 127.0.0.1 so the Capacitor frontend can talk to it
        uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")
        
    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()
    return "Server started"
