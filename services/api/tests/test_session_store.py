from pathlib import Path

import pytest

from app.core.session_store import (
    clear_session_cookie,
    has_session_cookie,
    save_session_cookie,
    scrub_cookie_values,
    session_cookie_file,
)

def test_save_and_detect_session_cookie(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    assert has_session_cookie(database, 'instagram') is False

    count = save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123; csrftoken=def456')

    assert count == 2
    assert has_session_cookie(database, 'instagram') is True


def test_save_session_cookie_rejects_empty_input(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    with pytest.raises(ValueError):
        save_session_cookie(database, 'instagram', '.instagram.com', '   ')


def test_saved_cookie_file_is_netscape_format_and_never_needs_reading_by_the_api(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')

    path = session_cookie_file(database, 'instagram')
    lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    assert lines == ['.instagram.com\tTRUE\t/\tTRUE\t' + lines[0].split('\t')[4] + '\tsessionid\tabc123']


def test_clear_session_cookie_removes_the_file(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')
    assert has_session_cookie(database, 'instagram') is True

    clear_session_cookie(database, 'instagram')

    assert has_session_cookie(database, 'instagram') is False


def test_clear_session_cookie_is_safe_when_no_file_exists(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    clear_session_cookie(database, 'instagram')  # must not raise


def test_scrub_cookie_values_redacts_leaked_session_value(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=super-secret-value')

    output = 'gallery-dl error: request failed with Cookie: sessionid=super-secret-value'
    scrubbed = scrub_cookie_values(output, database, 'instagram')

    assert 'super-secret-value' not in scrubbed
    assert '***REDACTED***' in scrubbed


def test_scrub_cookie_values_is_a_noop_when_no_cookie_is_stored(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    output = 'some unrelated error output'

    assert scrub_cookie_values(output, database, 'instagram') == output
