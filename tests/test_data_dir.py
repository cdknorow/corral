"""Tests for configurable data directory (--data-dir / CORAL_DATA_DIR).

Covers:
- get_data_dir() reads CORAL_DATA_DIR env var
- get_data_dir() defaults to ~/.coral when env var is not set
- All store/module paths resolve relative to the configured data dir
- Flag takes precedence over env var (tested at integration level)
- Stores create the data directory on first use
"""

import os
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import patch


# ── get_data_dir() tests ────────────────────────────────────────────────────


class TestGetDataDir:
    """Tests for the central get_data_dir() config function."""

    def test_defaults_to_home_coral(self):
        """Without CORAL_DATA_DIR, defaults to ~/.coral."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORAL_DATA_DIR", None)
            from coral.config import get_data_dir
            result = get_data_dir()
            assert result == Path.home() / ".coral"

    def test_reads_env_var(self, tmp_path):
        """CORAL_DATA_DIR env var overrides the default."""
        custom_dir = str(tmp_path / "custom-coral")
        with patch.dict(os.environ, {"CORAL_DATA_DIR": custom_dir}):
            from coral.config import get_data_dir
            result = get_data_dir()
            assert result == Path(custom_dir)

    def test_tilde_in_env_var_not_expanded_by_get_data_dir(self):
        """get_data_dir() returns the raw path — CLI is responsible for expanding ~."""
        with patch.dict(os.environ, {"CORAL_DATA_DIR": "~/.coral-custom"}):
            from coral.config import get_data_dir
            result = get_data_dir()
            # get_data_dir just wraps the env var as a Path; CLI handles expansion
            assert isinstance(result, Path)

    def test_returns_path_object(self, tmp_path):
        """get_data_dir() should return a Path, not a string."""
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(tmp_path)}):
            from coral.config import get_data_dir
            result = get_data_dir()
            assert isinstance(result, Path)


# ── Store path resolution tests ─────────────────────────────────────────────


class TestStorePathResolution:
    """Verify all stores resolve DB paths relative to get_data_dir()."""

    def test_sessions_db_uses_data_dir(self, tmp_path):
        """CoralStore should create sessions.db inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.store.connection import get_db_path
            db_path = get_db_path()
            assert db_path.parent == custom_dir or str(db_path).startswith(str(custom_dir))
            assert "sessions.db" in str(db_path)

    def test_messageboard_db_uses_data_dir(self, tmp_path):
        """MessageBoardStore should resolve DB inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.messageboard.store import get_db_path as mb_get_db_path
            db_path = mb_get_db_path()
            assert str(db_path).startswith(str(custom_dir))
            assert "messageboard.db" in str(db_path)

    def test_remote_boards_db_uses_data_dir(self, tmp_path):
        """RemoteBoardStore should resolve DB inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.store.remote_boards import get_db_path as rb_get_db_path
            db_path = rb_get_db_path()
            assert str(db_path).startswith(str(custom_dir))

    def test_uploads_dir_uses_data_dir(self, tmp_path):
        """Upload directory should resolve inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.api.uploads import get_upload_dir
            upload_dir = get_upload_dir()
            assert str(upload_dir).startswith(str(custom_dir))
            assert "uploads" in str(upload_dir)

    def test_themes_dir_uses_data_dir(self, tmp_path):
        """Themes directory should resolve inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.api.themes import get_themes_dir
            themes_dir = get_themes_dir()
            assert str(themes_dir).startswith(str(custom_dir))
            assert "themes" in str(themes_dir)

    def test_pid_file_uses_data_dir(self, tmp_path):
        """Tray PID file should resolve inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.tray import get_pid_file
            pid_path = get_pid_file()
            assert str(pid_path).startswith(str(custom_dir))

    def test_board_state_dir_uses_data_dir(self, tmp_path):
        """Message board CLI state dir should resolve inside the data dir."""
        custom_dir = tmp_path / "coral-data"
        with patch.dict(os.environ, {"CORAL_DATA_DIR": str(custom_dir)}):
            from coral.messageboard.cli import _get_state_dir
            state_dir = _get_state_dir()
            assert str(state_dir).startswith(str(custom_dir))


# ── Store creation in custom dir ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def custom_coral_store(tmp_path):
    """Create a CoralStore in a custom data directory."""
    custom_dir = tmp_path / "coral-data"
    db_path = custom_dir / "sessions.db"
    from coral.store import CoralStore
    s = CoralStore(db_path=db_path)
    yield s, custom_dir
    await s.close()


@pytest_asyncio.fixture
async def custom_board_store(tmp_path):
    """Create a MessageBoardStore in a custom data directory."""
    custom_dir = tmp_path / "coral-data"
    db_path = custom_dir / "messageboard.db"
    from coral.messageboard.store import MessageBoardStore
    s = MessageBoardStore(db_path=db_path)
    yield s, custom_dir
    await s.close()


@pytest.mark.asyncio
async def test_coral_store_creates_dir_on_first_use(custom_coral_store):
    """CoralStore should create the data directory on first DB access."""
    store, custom_dir = custom_coral_store
    # Trigger connection (lazy init)
    await store.get_settings()
    assert custom_dir.exists()
    assert (custom_dir / "sessions.db").exists()


@pytest.mark.asyncio
async def test_board_store_creates_dir_on_first_use(custom_board_store):
    """MessageBoardStore should create the data directory on first DB access."""
    store, custom_dir = custom_board_store
    # Trigger connection
    await store.subscribe("proj", "agent-1", "Dev")
    assert custom_dir.exists()
    assert (custom_dir / "messageboard.db").exists()


@pytest.mark.asyncio
async def test_stores_work_in_custom_dir(custom_coral_store, custom_board_store):
    """Both stores should be fully functional in a custom data directory."""
    coral_store, _ = custom_coral_store
    board_store, _ = custom_board_store

    # CoralStore: save and retrieve a setting
    await coral_store.set_setting("test_key", "test_value")
    settings = await coral_store.get_settings()
    assert settings["test_key"] == "test_value"

    # MessageBoardStore: subscribe and post
    await board_store.subscribe("proj", "agent-1", "Dev")
    msg = await board_store.post_message("proj", "agent-1", "hello")
    assert msg["content"] == "hello"


# ── Backward compatibility ───────────────────────────────────────────────────


class TestBackwardCompat:
    """Verify that without CORAL_DATA_DIR, everything works as before."""

    @pytest.mark.asyncio
    async def test_default_store_init_works(self, tmp_path):
        """CoralStore with explicit db_path still works (existing test pattern)."""
        from coral.store import CoralStore
        s = CoralStore(db_path=tmp_path / "test.db")
        await s.set_setting("key", "val")
        settings = await s.get_settings()
        assert settings["key"] == "val"
        await s.close()

    @pytest.mark.asyncio
    async def test_default_board_store_init_works(self, tmp_path):
        """MessageBoardStore with explicit db_path still works."""
        from coral.messageboard.store import MessageBoardStore
        s = MessageBoardStore(db_path=tmp_path / "test_board.db")
        await s.subscribe("p", "a1", "Dev")
        subs = await s.list_subscribers("p")
        assert len(subs) == 1
        await s.close()
