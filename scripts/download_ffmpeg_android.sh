#!/usr/bin/env bash
# Downloads statically compiled FFmpeg for Android (aarch64)

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BIN_DIR="$DIR/../apps/web/android/app/src/main/assets/bin"

mkdir -p "$BIN_DIR"

echo "Downloading FFmpeg for Android (aarch64)..."
curl -L -o "$BIN_DIR/ffmpeg" "https://github.com/Khang-NT/ffmpeg-binary-android/raw/master/app/src/main/jniLibs/arm64-v8a/libffmpeg.so"

echo "Downloading FFprobe for Android (aarch64)..."
curl -L -o "$BIN_DIR/ffprobe" "https://github.com/Khang-NT/ffmpeg-binary-android/raw/master/app/src/main/jniLibs/arm64-v8a/libffprobe.so"

echo "FFmpeg bundled successfully into $BIN_DIR"
