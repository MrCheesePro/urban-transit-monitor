import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_match_design() -> None:
    settings = Settings(_env_file=None)
    assert settings.on_time_early_seconds == -60
    assert settings.on_time_late_seconds == 300
    assert settings.timezone == "America/New_York"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON_TIME_LATE_SECONDS", "420")
    assert Settings(_env_file=None).on_time_late_seconds == 420


@pytest.mark.parametrize(("early", "late"), [(30, 300), (-60, -10)])
def test_rejects_window_not_containing_zero(early: int, late: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, on_time_early_seconds=early, on_time_late_seconds=late)
