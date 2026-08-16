# Termux installation

PocketDL is designed to follow the official yt-dlp Android path: Termux + Python + yt-dlp, with FFmpeg for post-processing. yt-dlp also supports concurrent HLS/DASH fragments and optional aria2 as an external downloader.

## One-time bootstrap

The installer will:

1. Request Termux storage permission.
2. Install Python, FFmpeg and aria2.
3. Install or upgrade yt-dlp.
4. Install the PocketDL Python service in a local application directory.
5. Create a launcher script.
6. Create a configuration file targeting `/sdcard/Download`.
7. Start the local web service.

The normal user workflow afterward is the web UI; Termux is only the host process.

## Security

The API binds to `127.0.0.1` by default. Do not expose it to a LAN or the public internet until authentication and an explicit bind setting are added.
