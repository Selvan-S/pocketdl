from pathlib import Path

from app.application.downloads.strategy import format_args, initial_attempt, impersonated_attempt
from app.domain.models import ImpersonationMode, RequestContext


def test_initial_strategy_is_standard_by_default() -> None:
    attempt = initial_attempt(RequestContext())
    assert attempt.label == 'standard'
    assert attempt.impersonate is None


def test_initial_strategy_can_use_chrome() -> None:
    attempt = initial_attempt(RequestContext(impersonation=ImpersonationMode.CHROME))
    assert attempt.label == 'impersonate:chrome'
    assert attempt.impersonate == 'chrome'


def test_impersonated_attempt_is_chrome() -> None:
    attempt = impersonated_attempt()
    assert attempt.impersonate == 'chrome'


def test_format_args_best_preset_has_no_height_cap() -> None:
    args = format_args('best')
    assert args == ['-f', 'bv*+ba/b', '--merge-output-format', 'mp4']


def test_format_args_720p_preset_caps_height() -> None:
    args = format_args('720p')
    assert args == ['-f', 'bv*[height<=720]+ba/b', '--merge-output-format', 'mp4']


def test_format_args_480p_preset_caps_height() -> None:
    args = format_args('480p')
    assert args == ['-f', 'bv*[height<=480]+ba/b', '--merge-output-format', 'mp4']


def test_format_args_audio_preset_extracts_mp3() -> None:
    args = format_args('audio')
    assert args == ['-f', 'ba/b', '-x', '--audio-format', 'mp3']


def test_format_args_specific_format_id_overrides_preset() -> None:
    # A 1080p-capped preset should not win over an explicit selection of a
    # higher-quality format from /api/analyze's list.
    args = format_args('1080p', format_id='299')
    assert args == ['-f', '299+bestaudio/best', '--merge-output-format', 'mp4']


def test_format_args_composite_format_id_is_allowed() -> None:
    # yt-dlp format_ids can already be a video+audio pair, e.g. "137+140".
    args = format_args('best', format_id='137+140')
    assert args[1] == '137+140+bestaudio/best'


def test_format_args_rejects_shell_metacharacters_and_falls_back_to_preset() -> None:
    # Defense in depth: the API layer validates this shape already, but a
    # malformed format_id must degrade to the preset rather than reach
    # yt-dlp's -f argument unescaped. asyncio.create_subprocess_exec never
    # invokes a shell, so this is not an injection vector either way, but a
    # value like this could still confuse yt-dlp's own -f parser.
    args = format_args('720p', format_id='137; rm -rf /')
    assert args == ['-f', 'bv*[height<=720]+ba/b', '--merge-output-format', 'mp4']


def test_format_args_empty_format_id_falls_back_to_preset() -> None:
    assert format_args('best', format_id='') == format_args('best', format_id=None)
