"""Tests for editable default prompts feature.

Covers:
- Storing/retrieving custom prompt settings via the store and API
- session_manager using custom prompts when set, falling back to defaults
- base.py _build_board_system_prompt using prompt overrides
- {board_name} template variable substitution in custom prompts
- Reset to default behavior (clearing custom settings)
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from coral.store import CoralStore
from coral.web_server import app


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def store(tmp_path):
    """Create a CoralStore backed by a temp DB."""
    s = CoralStore(db_path=tmp_path / "test.db")
    yield s
    await s.close()


# ── Store-level tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_default_prompt_settings_empty_by_default(store):
    """Settings should not contain prompt keys until explicitly set."""
    settings = await store.get_settings()
    assert "default_prompt_orchestrator" not in settings
    assert "default_prompt_worker" not in settings


@pytest.mark.asyncio
async def test_store_set_and_get_orchestrator_prompt(store):
    """Custom orchestrator prompt can be stored and retrieved."""
    custom = "Custom orchestrator instructions for {board_name}."
    await store.set_setting("default_prompt_orchestrator", custom)
    settings = await store.get_settings()
    assert settings["default_prompt_orchestrator"] == custom


@pytest.mark.asyncio
async def test_store_set_and_get_worker_prompt(store):
    """Custom worker prompt can be stored and retrieved."""
    custom = "Custom worker instructions for {board_name}."
    await store.set_setting("default_prompt_worker", custom)
    settings = await store.get_settings()
    assert settings["default_prompt_worker"] == custom


@pytest.mark.asyncio
async def test_store_update_prompt_overwrites(store):
    """Updating a prompt setting overwrites the previous value."""
    await store.set_setting("default_prompt_orchestrator", "v1")
    await store.set_setting("default_prompt_orchestrator", "v2")
    settings = await store.get_settings()
    assert settings["default_prompt_orchestrator"] == "v2"


@pytest.mark.asyncio
async def test_store_clear_prompt_by_setting_empty(store):
    """Setting a prompt to empty string effectively clears it."""
    await store.set_setting("default_prompt_worker", "something")
    await store.set_setting("default_prompt_worker", "")
    settings = await store.get_settings()
    assert settings["default_prompt_worker"] == ""


# ── API-level tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_put_and_get_prompt_settings():
    """PUT /api/settings with prompt keys, then GET to verify persistence."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "default_prompt_orchestrator": "API orchestrator prompt for {board_name}",
            "default_prompt_worker": "API worker prompt for {board_name}",
        }
        resp = await client.put("/api/settings", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        settings = resp.json()["settings"]
        assert settings["default_prompt_orchestrator"] == payload["default_prompt_orchestrator"]
        assert settings["default_prompt_worker"] == payload["default_prompt_worker"]


# ── _build_board_system_prompt tests ─────────────────────────────────────────


class TestBuildBoardSystemPrompt:
    """Tests for BaseAgent._build_board_system_prompt with prompt overrides."""

    def _import_base(self):
        from coral.agents.base import BaseAgent
        return BaseAgent

    def test_default_orchestrator_prompt_contains_key_phrases(self):
        """Default orchestrator system prompt mentions discussing plan with operator."""
        BaseAgent = self._import_base()
        result = BaseAgent._build_board_system_prompt("test-board", "Orchestrator", "Do stuff")
        assert "test-board" in result
        assert "discuss" in result.lower() or "plan" in result.lower()
        assert "coral-board" in result

    def test_default_worker_prompt_contains_key_phrases(self):
        """Default worker system prompt mentions waiting for Orchestrator."""
        BaseAgent = self._import_base()
        result = BaseAgent._build_board_system_prompt("test-board", "Backend Dev", "Do stuff")
        assert "test-board" in result
        assert "wait" in result.lower() or "Orchestrator" in result
        assert "coral-board" in result

    def test_no_board_returns_prompt_only(self):
        """Without a board, only the behavior prompt is returned."""
        BaseAgent = self._import_base()
        result = BaseAgent._build_board_system_prompt(None, None, "Just do this")
        assert result == "Just do this"

    def test_no_board_no_prompt_returns_empty(self):
        BaseAgent = self._import_base()
        result = BaseAgent._build_board_system_prompt(None, None, None)
        assert result == ""

    def test_orchestrator_vs_worker_prompts_differ(self):
        """Orchestrator and worker should get different instructions."""
        BaseAgent = self._import_base()
        orch = BaseAgent._build_board_system_prompt("b", "Orchestrator", "p")
        worker = BaseAgent._build_board_system_prompt("b", "Dev", "p")
        assert orch != worker

    def test_prompt_overrides_orchestrator(self):
        """Custom orchestrator override replaces the default tail text."""
        BaseAgent = self._import_base()
        overrides = {"default_prompt_orchestrator": "Custom orch instructions."}
        result = BaseAgent._build_board_system_prompt("board", "Orchestrator", "Do stuff", prompt_overrides=overrides)
        assert "Custom orch instructions." in result
        # Default tail should NOT be present
        from coral.agents.base import DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        assert DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT not in result

    def test_prompt_overrides_worker(self):
        """Custom worker override replaces the default tail text."""
        BaseAgent = self._import_base()
        overrides = {"default_prompt_worker": "Custom worker instructions."}
        result = BaseAgent._build_board_system_prompt("board", "Dev", "Do stuff", prompt_overrides=overrides)
        assert "Custom worker instructions." in result
        from coral.agents.base import DEFAULT_WORKER_SYSTEM_PROMPT
        assert DEFAULT_WORKER_SYSTEM_PROMPT not in result

    def test_prompt_overrides_empty_string_falls_back_to_default(self):
        """Empty string override should fall back to the default (falsy check)."""
        BaseAgent = self._import_base()
        from coral.agents.base import DEFAULT_WORKER_SYSTEM_PROMPT
        overrides = {"default_prompt_worker": ""}
        result = BaseAgent._build_board_system_prompt("board", "Dev", "Do stuff", prompt_overrides=overrides)
        assert DEFAULT_WORKER_SYSTEM_PROMPT in result

    def test_prompt_overrides_only_affects_matching_role(self):
        """Orchestrator override should not affect worker prompt."""
        BaseAgent = self._import_base()
        from coral.agents.base import DEFAULT_WORKER_SYSTEM_PROMPT
        overrides = {"default_prompt_orchestrator": "Custom orch only."}
        result = BaseAgent._build_board_system_prompt("board", "Dev", "Do stuff", prompt_overrides=overrides)
        # Worker should still get default since only orchestrator was overridden
        assert DEFAULT_WORKER_SYSTEM_PROMPT in result
        assert "Custom orch only." not in result


# ── setup_board_and_prompt integration tests ─────────────────────────────────


class TestSetupBoardPromptText:
    """Tests for the prompt text construction in setup_board_and_prompt.

    These test the prompt building logic — the actual tmux/send is mocked out.
    """

    def test_orchestrator_prompt_appended_text(self):
        """Verify the orchestrator append text format using the constant."""
        from coral.tools.session_manager import DEFAULT_ORCHESTRATOR_PROMPT
        board_name = "my-project"
        prompt = "You are an orchestrator."
        prompt += "\n\n" + DEFAULT_ORCHESTRATOR_PROMPT.format(board_name=board_name)

        assert f'message board "{board_name}"' in prompt
        assert "discuss your proposed plan" in prompt
        assert "Do NOT run coral-board join" in prompt

    def test_worker_prompt_appended_text(self):
        """Verify the worker append text format using the constant."""
        from coral.tools.session_manager import DEFAULT_WORKER_PROMPT
        board_name = "my-project"
        prompt = "You are a worker."
        prompt += "\n\n" + DEFAULT_WORKER_PROMPT.format(board_name=board_name)

        assert f'message board "{board_name}"' in prompt
        assert "receive instructions from the Orchestrator" in prompt
        assert "Do NOT run coral-board join" in prompt

    def test_board_name_substitution_in_custom_prompt(self):
        """Custom prompt with {board_name} placeholder should be substitutable."""
        custom_prompt = "You joined {board_name}. Follow the rules."
        board_name = "feature-xyz"
        result = custom_prompt.format(board_name=board_name)
        assert "feature-xyz" in result
        assert "{board_name}" not in result

    def test_board_name_substitution_no_placeholder(self):
        """Custom prompt without {board_name} should work fine (no crash)."""
        custom_prompt = "Just follow the rules, no board ref."
        board_name = "feature-xyz"
        # Should not raise
        result = custom_prompt.format(board_name=board_name)
        assert result == custom_prompt

    def test_board_name_substitution_multiple_placeholders(self):
        """Multiple {board_name} placeholders should all be replaced."""
        custom_prompt = "Board is {board_name}. Remember: {board_name}!"
        result = custom_prompt.format(board_name="proj")
        assert result == "Board is proj. Remember: proj!"


# ── Default constants tests ──────────────────────────────────────────────────


class TestDefaultPromptConstants:
    """Once the refactor is done, DEFAULT_ORCHESTRATOR_PROMPT and
    DEFAULT_WORKER_PROMPT constants should exist for frontend reset-to-default.

    These tests will pass after Backend Dev extracts the constants.
    """

    def test_default_orchestrator_constant_exists(self):
        from coral.tools.session_manager import DEFAULT_ORCHESTRATOR_PROMPT
        assert isinstance(DEFAULT_ORCHESTRATOR_PROMPT, str)
        assert len(DEFAULT_ORCHESTRATOR_PROMPT) > 20
        assert "{board_name}" in DEFAULT_ORCHESTRATOR_PROMPT

    def test_default_worker_constant_exists(self):
        from coral.tools.session_manager import DEFAULT_WORKER_PROMPT
        assert isinstance(DEFAULT_WORKER_PROMPT, str)
        assert len(DEFAULT_WORKER_PROMPT) > 20
        assert "{board_name}" in DEFAULT_WORKER_PROMPT

    @pytest.mark.asyncio
    async def test_defaults_endpoint_exposes_constants(self):
        """The API should expose default prompt constants for frontend reset."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/settings/default-prompts")
            assert resp.status_code == 200
            data = resp.json()
            assert "default_prompt_orchestrator" in data
            assert "default_prompt_worker" in data
            assert "{board_name}" in data["default_prompt_orchestrator"]
            assert "{board_name}" in data["default_prompt_worker"]
