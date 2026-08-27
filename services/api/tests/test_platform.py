import builtins
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.platform import DirectoryPickerUnavailable, browse_for_directory


def test_browse_for_directory_returns_the_chosen_path() -> None:
    with patch('tkinter.filedialog.askdirectory', return_value='C:/Users/PC/Downloads/PocketDL'):
        assert browse_for_directory(Path('C:/Users/PC/Downloads')) == 'C:/Users/PC/Downloads/PocketDL'


def test_browse_for_directory_returns_none_when_cancelled() -> None:
    # tkinter's askdirectory returns '' (not None) when the user cancels.
    with patch('tkinter.filedialog.askdirectory', return_value=''):
        assert browse_for_directory() is None


def test_browse_for_directory_raises_when_tkinter_is_unavailable() -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'tkinter':
            raise ImportError('no display')
        return real_import(name, *args, **kwargs)

    with patch('builtins.__import__', side_effect=fake_import):
        with pytest.raises(DirectoryPickerUnavailable):
            browse_for_directory()
