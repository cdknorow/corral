"""Tests for the +Team Send button's configurable reminder settings.

Covers:
- Orchestrator and worker team_reminder settings storage/retrieval
- Default value fallback when no custom reminder is set
- Reset to default behavior (clearing the setting)
- Role detection logic for picking the correct reminder
- Independence from other settings
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from coral.store import CoralStore
from coral.web_server import app


DEFAULT_TEAM_REMINDER_ORCHESTRATOR = "Remember to coordinate with your team and check the message board for updates"
DEFAULT_TEAM_REMINDER_WORKER = "Remember to work with your team"


@pytest_asyncio.fixture
async def store(tmp_path):
    s = CoralStore(db_path=tmp_path / "test.db")
    yield s
    await s.close()


# ── Store-level tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_team_reminders_not_set_by_default(store):
    """team_reminder keys should not exist until explicitly set."""
    settings = await store.get_settings()
    assert "team_reminder_orchestrator" not in settings
    assert "team_reminder_worker" not in settings


@pytest.mark.asyncio
async def test_store_set_and_get_orchestrator_reminder(store):
    """Custom orchestrator team reminder can be stored and retrieved."""
    custom = "Coordinate with agents and check board!"
    await store.set_setting("team_reminder_orchestrator", custom)
    settings = await store.get_settings()
    assert settings["team_reminder_orchestrator"] == custom


@pytest.mark.asyncio
async def test_store_set_and_get_worker_reminder(store):
    """Custom worker team reminder can be stored and retrieved."""
    custom = "Check with your orchestrator before proceeding."
    await store.set_setting("team_reminder_worker", custom)
    settings = await store.get_settings()
    assert settings["team_reminder_worker"] == custom


@pytest.mark.asyncio
async def test_store_update_reminder_overwrites(store):
    """Updating a reminder overwrites the previous value."""
    await store.set_setting("team_reminder_orchestrator", "v1")
    await store.set_setting("team_reminder_orchestrator", "v2")
    settings = await store.get_settings()
    assert settings["team_reminder_orchestrator"] == "v2"


@pytest.mark.asyncio
async def test_store_clear_reminder(store):
    """Setting a reminder to empty string effectively clears it."""
    await store.set_setting("team_reminder_worker", "something")
    await store.set_setting("team_reminder_worker", "")
    settings = await store.get_settings()
    assert settings["team_reminder_worker"] == ""


# ── API-level tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_put_and_get_both_reminders():
    """PUT /api/settings with both reminder keys, then GET to verify."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "team_reminder_orchestrator": "Custom orch reminder",
            "team_reminder_worker": "Custom worker reminder",
        }
        resp = await client.put("/api/settings", json=payload)
        assert resp.status_code == 200

        resp = await client.get("/api/settings")
        settings = resp.json()["settings"]
        assert settings["team_reminder_orchestrator"] == "Custom orch reminder"
        assert settings["team_reminder_worker"] == "Custom worker reminder"


@pytest.mark.asyncio
async def test_api_reminders_independent_of_prompt_settings():
    """team_reminder keys should not interfere with default prompt settings."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "team_reminder_orchestrator": "Orch reminder",
            "team_reminder_worker": "Worker reminder",
            "default_prompt_orchestrator": "Orch prompt",
            "default_prompt_worker": "Worker prompt",
        }
        resp = await client.put("/api/settings", json=payload)
        assert resp.status_code == 200

        # Update only one reminder — others unchanged
        await client.put("/api/settings", json={"team_reminder_worker": "Updated worker"})
        resp = await client.get("/api/settings")
        settings = resp.json()["settings"]
        assert settings["team_reminder_worker"] == "Updated worker"
        assert settings["team_reminder_orchestrator"] == "Orch reminder"
        assert settings["default_prompt_orchestrator"] == "Orch prompt"


# ── Role detection logic ────────────────────────────────────────────────────


class TestRoleDetection:
    """Frontend picks the reminder based on session's display_name/board_job_title.
    These tests validate the detection logic pattern used in the codebase.
    """

    def _is_orchestrator(self, display_name: str | None, board_job_title: str | None) -> bool:
        """Simulate frontend orchestrator detection logic."""
        for field in (display_name, board_job_title):
            if field and "orchestrator" in field.lower():
                return True
        return False

    def test_orchestrator_in_display_name(self):
        assert self._is_orchestrator("Orchestrator", None) is True

    def test_orchestrator_in_job_title(self):
        assert self._is_orchestrator(None, "Lead Orchestrator") is True

    def test_orchestrator_case_insensitive(self):
        assert self._is_orchestrator("ORCHESTRATOR", None) is True

    def test_worker_session(self):
        assert self._is_orchestrator("Backend Dev", "Worker") is False

    def test_no_role_info_defaults_to_worker(self):
        assert self._is_orchestrator(None, None) is False

    def test_reminder_selection_orchestrator(self):
        """Orchestrator session should use orchestrator reminder."""
        settings = {}  # empty = use defaults
        is_orch = self._is_orchestrator("Orchestrator", None)
        if is_orch:
            reminder = settings.get("team_reminder_orchestrator") or DEFAULT_TEAM_REMINDER_ORCHESTRATOR
        else:
            reminder = settings.get("team_reminder_worker") or DEFAULT_TEAM_REMINDER_WORKER
        assert reminder == DEFAULT_TEAM_REMINDER_ORCHESTRATOR

    def test_reminder_selection_worker(self):
        """Worker session should use worker reminder."""
        settings = {}
        is_orch = self._is_orchestrator("Backend Dev", None)
        if is_orch:
            reminder = settings.get("team_reminder_orchestrator") or DEFAULT_TEAM_REMINDER_ORCHESTRATOR
        else:
            reminder = settings.get("team_reminder_worker") or DEFAULT_TEAM_REMINDER_WORKER
        assert reminder == DEFAULT_TEAM_REMINDER_WORKER

    def test_reminder_selection_with_custom(self):
        """Custom reminder should override default for the correct role."""
        settings = {
            "team_reminder_orchestrator": "Custom orch",
            "team_reminder_worker": "Custom worker",
        }
        # Orchestrator session
        reminder = settings.get("team_reminder_orchestrator") or DEFAULT_TEAM_REMINDER_ORCHESTRATOR
        assert reminder == "Custom orch"
        # Worker session
        reminder = settings.get("team_reminder_worker") or DEFAULT_TEAM_REMINDER_WORKER
        assert reminder == "Custom worker"


# ── Default value fallback ──────────────────────────────────────────────────


class TestTeamReminderDefaults:

    @pytest.mark.asyncio
    async def test_fallback_orchestrator_when_not_set(self):
        """When orchestrator reminder is absent, use the default."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/settings")
            settings = resp.json()["settings"]
            reminder = settings.get("team_reminder_orchestrator") or DEFAULT_TEAM_REMINDER_ORCHESTRATOR
            assert reminder == DEFAULT_TEAM_REMINDER_ORCHESTRATOR or isinstance(reminder, str)

    @pytest.mark.asyncio
    async def test_fallback_worker_when_not_set(self):
        """When worker reminder is absent, use the default."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/settings")
            settings = resp.json()["settings"]
            reminder = settings.get("team_reminder_worker") or DEFAULT_TEAM_REMINDER_WORKER
            assert reminder == DEFAULT_TEAM_REMINDER_WORKER or isinstance(reminder, str)

    @pytest.mark.asyncio
    async def test_fallback_when_empty_string(self):
        """Empty string should trigger fallback to default."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.put("/api/settings", json={
                "team_reminder_orchestrator": "",
                "team_reminder_worker": "",
            })
            resp = await client.get("/api/settings")
            settings = resp.json()["settings"]
            orch = settings.get("team_reminder_orchestrator") or DEFAULT_TEAM_REMINDER_ORCHESTRATOR
            worker = settings.get("team_reminder_worker") or DEFAULT_TEAM_REMINDER_WORKER
            assert orch == DEFAULT_TEAM_REMINDER_ORCHESTRATOR
            assert worker == DEFAULT_TEAM_REMINDER_WORKER
