import pytest
from pydantic import ValidationError

from app.core.config import Settings


# The defaults must match the values documented in docs/DESIGN.md.
def test_defaults_match_design() -> None:
    settings = Settings(_env_file=None)
    assert settings.on_time_early_seconds == -60
    assert settings.on_time_late_seconds == 300
    assert settings.timezone == "America/New_York"


# Environment variables override the defaults.
def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON_TIME_LATE_SECONDS", "420")
    assert Settings(_env_file=None).on_time_late_seconds == 420


# An on-time window that does not contain zero is rejected at startup.
@pytest.mark.parametrize(("early", "late"), [(30, 300), (-60, -10)])
def test_rejects_window_not_containing_zero(early: int, late: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, on_time_early_seconds=early, on_time_late_seconds=late)
