from pathlib import Path

from app.application.downloads.strategy import initial_attempt, impersonated_attempt
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
