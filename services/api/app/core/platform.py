import os
import platform
import subprocess
from pathlib import Path


class DirectoryPickerUnavailable(RuntimeError):
    """No display/tkinter available to show a native folder dialog --
    expected on Termux or any other headless environment."""


def browse_for_directory(initial_directory: Path | None = None) -> str | None:
    """Open a native OS folder picker on the machine running the backend
    and return the chosen absolute path, or None if the user cancelled.

    Desktop-only. The backend and the browser are typically the same
    machine for desktop use, which is what makes this possible at all --
    a browser page cannot get a real OS path from a folder picker itself
    (see the File System Access API's sandboxed-handle limitation), but
    the local Python process can show one directly. Raises
    DirectoryPickerUnavailable rather than a generic error when there is
    no display to show a window on (Termux, headless CI, etc.), so the API
    layer can return a distinct, expected status rather than a 500.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise DirectoryPickerUnavailable('A native folder picker is not available on this system.') from exc

    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        raise DirectoryPickerUnavailable('No display is available to show a folder picker.') from exc

    try:
        root.withdraw()
        root.attributes('-topmost', True)
        chosen = filedialog.askdirectory(
            initialdir=str(initial_directory) if initial_directory else None,
            mustexist=True,
        )
    finally:
        root.destroy()

    return chosen or None  # askdirectory returns '' when the user cancels


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
