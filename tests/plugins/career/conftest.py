import pytest

from edith.plugins.career import profile


@pytest.fixture(autouse=True)
def example_career_profile(monkeypatch):
    monkeypatch.setenv("EDITH_CAREER_PROFILE", str(profile.EXAMPLE_PATH))
    return profile.require()
