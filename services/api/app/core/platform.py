import os
import platform
import subprocess
from pathlib import Path


def open_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    system = platform.system()
    if system == 'Windows':
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == 'Darwin':
        subprocess.Popen(['open', str(path)])
    else:
        # On Termux this may use termux-open when available; otherwise fall back
        # to xdg-open on regular Linux environments.
        if subprocess.run(['sh', '-lc', 'command -v termux-open >/dev/null 2>&1'], check=False).returncode == 0:
            subprocess.Popen(['termux-open', str(path)])
        else:
            subprocess.Popen(['xdg-open', str(path)])
