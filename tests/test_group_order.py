"""Tests for sidebar session group reordering (group_order setting).

Covers:
- group_order setting storage/retrieval as JSON array
- Default state (no group_order) — groups unordered
- Sorting logic: known groups in order, unknown groups appended
- Edge cases: move top up, move bottom down, new/removed groups
- Persistence across page reloads (settings round-trip)
"""

import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from coral.store import CoralStore
from coral.web_server import app


@pytest_asyncio.fixture
async def store(tmp_path):
    s = CoralStore(db_path=tmp_path / "test.db")
    yield s
    await s.close()


# ── Store-level tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_group_order_not_set_by_default(store):
    """group_order should not exist until explicitly set."""
    settings = await store.get_settings()
    assert "group_order" not in settings


@pytest.mark.asyncio
async def test_store_set_and_get_group_order(store):
    """group_order stored as JSON string, retrieved correctly."""
    order = ["MAIN", "GO-WORKTREE", "TMP"]
    await store.set_setting("group_order", json.dumps(order))
    settings = await store.get_settings()
    assert json.loads(settings["group_order"]) == order


@pytest.mark.asyncio
async def test_store_update_group_order(store):
    """Updating group_order replaces the previous value."""
    await store.set_setting("group_order", json.dumps(["A", "B"]))
    await store.set_setting("group_order", json.dumps(["B", "A"]))
    settings = await store.get_settings()
    assert json.loads(settings["group_order"]) == ["B", "A"]


# ── API-level tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_put_and_get_group_order():
    """PUT /api/settings with group_order JSON, then GET to verify."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        order = ["MAIN", "WORKTREE-1", "WORKTREE-2"]
        payload = {"group_order": json.dumps(order)}
        resp = await client.put("/api/settings", json=payload)
        assert resp.status_code == 200

        resp = await client.get("/api/settings")
        settings = resp.json()["settings"]
        assert json.loads(settings["group_order"]) == order


@pytest.mark.asyncio
async def test_api_group_order_independent_of_other_settings():
    """group_order should not interfere with other settings."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.put("/api/settings", json={
            "group_order": json.dumps(["A", "B"]),
            "team_reminder_worker": "reminder",
        })
        resp = await client.get("/api/settings")
        settings = resp.json()["settings"]
        assert json.loads(settings["group_order"]) == ["A", "B"]
        assert settings["team_reminder_worker"] == "reminder"


# ── Sorting logic (simulating frontend) ─────────────────────────────────────


class TestGroupSorting:
    """Test the sorting logic that the frontend implements."""

    def _sort_groups(self, group_entries: list[tuple[str, list]], saved_order: list[str] | None) -> list[tuple[str, list]]:
        """Simulate frontend _sortGroups logic."""
        if not saved_order:
            return group_entries
        order_map = {name: i for i, name in enumerate(saved_order)}
        max_idx = len(saved_order)
        return sorted(group_entries, key=lambda e: order_map.get(e[0], max_idx))

    def test_no_saved_order_preserves_insertion_order(self):
        """Without group_order, groups stay in original order."""
        groups = [("C", []), ("A", []), ("B", [])]
        result = self._sort_groups(groups, None)
        assert [g[0] for g in result] == ["C", "A", "B"]

    def test_saved_order_sorts_groups(self):
        """Groups are sorted according to saved order."""
        groups = [("C", []), ("A", []), ("B", [])]
        result = self._sort_groups(groups, ["A", "B", "C"])
        assert [g[0] for g in result] == ["A", "B", "C"]

    def test_unknown_groups_appended_at_end(self):
        """Groups not in saved order appear after known groups."""
        groups = [("NEW", []), ("A", []), ("B", [])]
        result = self._sort_groups(groups, ["A", "B"])
        assert [g[0] for g in result] == ["A", "B", "NEW"]

    def test_removed_groups_ignored(self):
        """Groups in saved order but not in current entries are just skipped."""
        groups = [("A", []), ("C", [])]
        result = self._sort_groups(groups, ["A", "B", "C"])
        assert [g[0] for g in result] == ["A", "C"]


class TestGroupMoveOperations:
    """Test move up/down logic."""

    def _move_up(self, order: list[str], group_name: str) -> list[str]:
        """Simulate moveGroupUp."""
        idx = order.index(group_name)
        if idx <= 0:
            return order
        new_order = order[:]
        new_order[idx - 1], new_order[idx] = new_order[idx], new_order[idx - 1]
        return new_order

    def _move_down(self, order: list[str], group_name: str) -> list[str]:
        """Simulate moveGroupDown."""
        idx = order.index(group_name)
        if idx >= len(order) - 1:
            return order
        new_order = order[:]
        new_order[idx], new_order[idx + 1] = new_order[idx + 1], new_order[idx]
        return new_order

    def test_move_up(self):
        result = self._move_up(["A", "B", "C"], "B")
        assert result == ["B", "A", "C"]

    def test_move_down(self):
        result = self._move_down(["A", "B", "C"], "B")
        assert result == ["A", "C", "B"]

    def test_move_top_up_noop(self):
        """Moving the top group up should be a no-op."""
        result = self._move_up(["A", "B", "C"], "A")
        assert result == ["A", "B", "C"]

    def test_move_bottom_down_noop(self):
        """Moving the bottom group down should be a no-op."""
        result = self._move_down(["A", "B", "C"], "C")
        assert result == ["A", "B", "C"]

    def test_move_preserves_other_elements(self):
        """Move operations should not add/remove elements."""
        order = ["A", "B", "C", "D"]
        result = self._move_up(order, "C")
        assert sorted(result) == ["A", "B", "C", "D"]
        assert result == ["A", "C", "B", "D"]
