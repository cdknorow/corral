"""Tests for ScheduleStore and schedule API endpoints."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from coral.store.schedule import ScheduleStore
from coral.store.connection import DatabaseManager


@pytest_asyncio.fixture
async def schedule_store(tmp_path):
    db_path = tmp_path / "test.db"
    store = ScheduleStore(db_path)
    # Force schema creation
    await store._get_conn()
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_create_and_list_jobs(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Nightly Tests",
        cron_expr="0 2 * * *",
        repo_path="/tmp/test-repo",
        prompt="Run all tests",
        description="Runs every night",
    )
    assert job["name"] == "Nightly Tests"
    assert job["cron_expr"] == "0 2 * * *"
    assert job["enabled"] == 1

    jobs = await schedule_store.list_scheduled_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "Nightly Tests"


@pytest.mark.asyncio
async def test_list_enabled_only(schedule_store):
    await schedule_store.create_scheduled_job(
        name="Enabled", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p", enabled=True,
    )
    await schedule_store.create_scheduled_job(
        name="Disabled", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p", enabled=False,
    )
    all_jobs = await schedule_store.list_scheduled_jobs()
    assert len(all_jobs) == 2

    enabled = await schedule_store.list_scheduled_jobs(enabled_only=True)
    assert len(enabled) == 1
    assert enabled[0]["name"] == "Enabled"


@pytest.mark.asyncio
async def test_update_job(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Test", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p",
    )
    updated = await schedule_store.update_scheduled_job(job["id"], name="Updated", enabled=False)
    assert updated["name"] == "Updated"
    assert updated["enabled"] == 0


@pytest.mark.asyncio
async def test_delete_job(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Test", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p",
    )
    await schedule_store.delete_scheduled_job(job["id"])
    jobs = await schedule_store.list_scheduled_jobs()
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_create_and_list_runs(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Test", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p",
    )
    run_id = await schedule_store.create_scheduled_run(
        job["id"], "2024-01-01T02:00:00+00:00"
    )
    assert run_id is not None

    runs = await schedule_store.get_runs_for_job(job["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_update_run(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Test", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p",
    )
    run_id = await schedule_store.create_scheduled_run(
        job["id"], "2024-01-01T02:00:00+00:00"
    )
    await schedule_store.update_scheduled_run(
        run_id, status="running", session_id="abc-123",
        started_at="2024-01-01T02:00:05+00:00",
    )
    last = await schedule_store.get_last_run_for_job(job["id"])
    assert last["status"] == "running"
    assert last["session_id"] == "abc-123"


@pytest.mark.asyncio
async def test_active_run_detection(schedule_store):
    job = await schedule_store.create_scheduled_job(
        name="Test", cron_expr="0 * * * *",
        repo_path="/tmp/r", prompt="p",
    )
    # No active run initially
    assert await schedule_store.get_active_run_for_job(job["id"]) is None

    run_id = await schedule_store.create_scheduled_run(
        job["id"], "2024-01-01T02:00:00+00:00"
    )
    # Pending run counts as active
    active = await schedule_store.get_active_run_for_job(job["id"])
    assert active is not None

    # Mark completed
    await schedule_store.update_scheduled_run(run_id, status="completed")
    assert await schedule_store.get_active_run_for_job(job["id"]) is None


# ── API endpoint tests ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_client(tmp_path):
    from coral.web_server import app, _set_store, _set_schedule_store
    from coral.store import CoralStore

    db_path = tmp_path / "api_test.db"
    store = CoralStore(db_path)
    sched_store = ScheduleStore(db_path)
    _set_store(store)
    _set_schedule_store(sched_store)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await store.close()
    await sched_store.close()


@pytest.mark.asyncio
async def test_api_create_and_list_jobs(api_client):
    # Create a job
    resp = await api_client.post("/api/scheduled/jobs", json={
        "name": "API Test",
        "cron_expr": "0 3 * * *",
        "repo_path": "/tmp/test",
        "prompt": "run tests",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "API Test"
    job_id = data["id"]

    # List jobs
    resp = await api_client.get("/api/scheduled/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id


@pytest.mark.asyncio
async def test_api_validate_cron(api_client):
    # Valid
    resp = await api_client.post("/api/scheduled/validate-cron", json={
        "cron_expr": "0 2 * * *",
    })
    data = resp.json()
    assert data["valid"] is True
    assert len(data["next_fire_times"]) == 5

    # Invalid
    resp = await api_client.post("/api/scheduled/validate-cron", json={
        "cron_expr": "bad",
    })
    data = resp.json()
    assert data["valid"] is False


@pytest.mark.asyncio
async def test_api_toggle_job(api_client):
    resp = await api_client.post("/api/scheduled/jobs", json={
        "name": "Toggle Test",
        "cron_expr": "0 * * * *",
        "repo_path": "/tmp/t",
        "prompt": "p",
    })
    job_id = resp.json()["id"]

    # Toggle off
    resp = await api_client.post(f"/api/scheduled/jobs/{job_id}/toggle")
    assert resp.json()["enabled"] == 0

    # Toggle on
    resp = await api_client.post(f"/api/scheduled/jobs/{job_id}/toggle")
    assert resp.json()["enabled"] == 1


@pytest.mark.asyncio
async def test_api_delete_job(api_client):
    resp = await api_client.post("/api/scheduled/jobs", json={
        "name": "Delete Me",
        "cron_expr": "0 * * * *",
        "repo_path": "/tmp/t",
        "prompt": "p",
    })
    job_id = resp.json()["id"]

    resp = await api_client.delete(f"/api/scheduled/jobs/{job_id}")
    assert resp.json()["ok"] is True

    resp = await api_client.get("/api/scheduled/jobs")
    assert len(resp.json()["jobs"]) == 0
