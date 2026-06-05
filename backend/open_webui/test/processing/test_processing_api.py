"""
Unit tests for document processing API endpoints.

Tests the REST API endpoints in routers/processing.py.
"""

import pytest
import time
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from open_webui.routers.processing import router
from open_webui.models.processing import (
    ProcessingTask,
    ProcessingTasks,
    ProcessingTaskResponse,
    ProcessingTaskListResponse,
    ProcessingMetrics,
    ProcessingStatus,
    ProcessingStage,
    DocumentType,
    can_cancel,
)
from open_webui.utils.auth import get_admin_user
from open_webui.internal.db import get_async_session


# Create a test app with the router
app = FastAPI()
app.include_router(router)


# Per-test overridable containers. `patch('...')` context managers still used
# in existing tests set `return_value` on these lambdas via dependency_overrides.
_current_admin = None
_current_db = None


def _get_admin_override():
    return _current_admin


def _get_async_session_override():
    return _current_db


app.dependency_overrides[get_admin_user] = _get_admin_override
app.dependency_overrides[get_async_session] = _get_async_session_override


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Reset per-test override state."""
    global _current_admin, _current_db
    yield
    _current_admin = None
    _current_db = None


def _make_async_db(mock_task=None, scalar_all=None, scalar_value=0):
    """Create a mock AsyncSession with configurable .get() and .execute() responses.

    - mock_task: value returned by awaiting db.get(...)
    - scalar_all: list returned by result.scalars().all()
    - scalar_value: value returned by result.scalar() (count queries)
    """
    mock_db = MagicMock()
    mock_db.get = AsyncMock(return_value=mock_task)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = scalar_all if scalar_all is not None else []
    mock_scalars.first.return_value = mock_task
    mock_result.scalars.return_value = mock_scalars
    mock_result.scalar.return_value = scalar_value
    mock_result.scalar_one_or_none.return_value = mock_task

    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    user = MagicMock()
    user.id = "admin-123"
    user.role = "admin"
    return user


@pytest.fixture
def mock_task():
    """Create a mock processing task."""
    task = MagicMock(spec=ProcessingTask)
    task.id = "task-123"
    task.document_id = "doc-456"
    task.document_name = "test.pdf"
    task.document_type = DocumentType.FILE_UPLOAD.value
    task.user_id = "user-789"
    task.chat_id = None
    task.status = ProcessingStatus.PROCESSING.value
    task.stage = ProcessingStage.EMBEDDING.value
    task.progress = 0.5
    task.created_at = int(time.time()) - 60
    task.started_at = int(time.time()) - 50
    task.completed_at = None
    task.total_chunks = 100
    task.processed_chunks = 50
    task.retry_count = 0
    task.error_message = None
    task.cancel_requested = False
    task.meta = {}
    return task


@pytest.fixture
def mock_failed_task():
    """Create a mock failed processing task."""
    task = MagicMock(spec=ProcessingTask)
    task.id = "task-failed"
    task.document_id = "doc-456"
    task.document_name = "test.pdf"
    task.document_type = DocumentType.FILE_UPLOAD.value
    task.user_id = "user-789"
    task.chat_id = None
    task.status = ProcessingStatus.FAILED.value
    task.stage = ProcessingStage.FAILED.value
    task.progress = 0.3
    task.created_at = int(time.time()) - 120
    task.started_at = int(time.time()) - 110
    task.completed_at = int(time.time()) - 10
    task.total_chunks = 100
    task.processed_chunks = 30
    task.retry_count = 1
    task.error_message = "Connection timeout"
    task.cancel_requested = False
    task.meta = {}
    return task


class TestListProcessingTasks:
    """Tests for GET /tasks endpoint."""

    def test_list_tasks_returns_list(self, mock_admin_user, mock_task):
        """Test that list endpoint returns task list."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task, scalar_all=[mock_task], scalar_value=1)
        _current_db = mock_db

        client = TestClient(app)
        response = client.get("/tasks")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1

    def test_list_tasks_with_status_filter(self, mock_admin_user, mock_task):
        """Test filtering tasks by status."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task, scalar_all=[mock_task], scalar_value=1)
        _current_db = mock_db

        client = TestClient(app)
        response = client.get("/tasks?status=processing")

        assert response.status_code == 200

    def test_list_tasks_with_pagination(self, mock_admin_user, mock_task):
        """Test pagination parameters."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task, scalar_all=[mock_task], scalar_value=100)
        _current_db = mock_db

        client = TestClient(app)
        response = client.get("/tasks?limit=10&offset=20")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 20


class TestGetProcessingTask:
    """Tests for GET /tasks/{task_id} endpoint."""

    def test_get_task_success(self, mock_admin_user, mock_task):
        """Test getting a single task."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        client = TestClient(app)
        response = client.get("/tasks/task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "task-123"

    def test_get_task_not_found(self, mock_admin_user):
        """Test getting a non-existent task."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=None)
        _current_db = mock_db

        client = TestClient(app)
        response = client.get("/tasks/nonexistent")

        assert response.status_code == 404


class TestCancelProcessingTask:
    """Tests for POST /tasks/{task_id}/cancel endpoint."""

    def test_cancel_task_success(self, mock_admin_user, mock_task):
        """Test cancelling an active task."""
        mock_task.stage = ProcessingStage.EMBEDDING.value
        mock_task.cancel_requested = False

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        client = TestClient(app)
        response = client.post("/tasks/task-123/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert mock_task.cancel_requested is True

    def test_cancel_task_not_found(self, mock_admin_user):
        """Test cancelling a non-existent task."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=None)
        _current_db = mock_db

        client = TestClient(app)
        response = client.post("/tasks/nonexistent/cancel")

        assert response.status_code == 404

    def test_cancel_completed_task_fails(self, mock_admin_user, mock_task):
        """Test that cancelling a completed task fails."""
        mock_task.stage = ProcessingStage.COMPLETED.value

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        client = TestClient(app)
        response = client.post("/tasks/task-123/cancel")

        assert response.status_code == 400


class TestRetryProcessingTask:
    """Tests for POST /tasks/{task_id}/retry endpoint."""

    def test_retry_failed_task_success(self, mock_admin_user, mock_failed_task):
        """Test retrying a failed task."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_failed_task)
        _current_db = mock_db

        mock_file = MagicMock(id="doc-456", user_id="user-789", filename="test.pdf")
        # meta must be a real dict: reprocess_file() does file.meta.get("collection_name")
        # and feeds it into ProcessFileForm, which Pydantic rejects if it is a MagicMock.
        mock_file.meta = {"collection_name": "test-collection"}
        with patch('open_webui.models.files.Files.get_file_by_id', new=AsyncMock(return_value=mock_file)), \
             patch('open_webui.routers.processing.Users.get_user_by_id', return_value=MagicMock(id="user-789")), \
             patch.object(ProcessingTasks, 'retry_task', new=AsyncMock()) as mock_retry:
            mock_failed_task.retry_count = 2
            mock_retry.return_value = mock_failed_task

            client = TestClient(app)
            response = client.post("/tasks/task-failed/retry")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["retry_count"] == 2

    def test_retry_active_task_fails(self, mock_admin_user, mock_task):
        """Test that retrying an active task fails."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'retry_task', new=AsyncMock()) as mock_retry:
            mock_retry.return_value = None  # Task not retryable

            client = TestClient(app)
            response = client.post("/tasks/task-123/retry")

            assert response.status_code == 400


class TestDeleteProcessingTask:
    """Tests for DELETE /tasks/{task_id} endpoint."""

    def test_delete_completed_task_success(self, mock_admin_user, mock_task):
        """Test deleting a completed task."""
        mock_task.status = ProcessingStatus.COMPLETED.value

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'delete_task', new=AsyncMock()) as mock_delete:
            mock_delete.return_value = True

            client = TestClient(app)
            response = client.delete("/tasks/task-123")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_delete_active_task_fails(self, mock_admin_user, mock_task):
        """Test that deleting an active task fails."""
        mock_task.status = ProcessingStatus.PROCESSING.value

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        client = TestClient(app)
        response = client.delete("/tasks/task-123")

        assert response.status_code == 400


class TestGetProcessingMetrics:
    """Tests for GET /metrics endpoint."""

    def test_get_metrics_success(self, mock_admin_user):
        """Test getting processing metrics."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db()
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'get_metrics', new=AsyncMock()) as mock_metrics:
            mock_metrics.return_value = ProcessingMetrics(
                total_tasks=100,
                queued=5,
                processing=10,
                completed=80,
                failed=3,
                cancelled=2,
                avg_processing_time=45.5,
                success_rate=94.1,
            )

            client = TestClient(app)
            response = client.get("/metrics?time_range=24h")

            assert response.status_code == 200
            data = response.json()
            assert data["total_tasks"] == 100
            assert data["completed"] == 80

    def test_get_metrics_different_time_ranges(self, mock_admin_user):
        """Test getting metrics with different time ranges."""
        time_ranges = ["1h", "24h", "7d", "30d"]

        for time_range in time_ranges:
            global _current_admin, _current_db
            _current_admin = mock_admin_user
            mock_db = _make_async_db()
            _current_db = mock_db

            with patch.object(ProcessingTasks, 'get_metrics', new=AsyncMock()) as mock_metrics:
                mock_metrics.return_value = ProcessingMetrics(
                    total_tasks=100,
                    queued=5,
                    processing=10,
                    completed=80,
                    failed=3,
                    cancelled=2,
                )

                client = TestClient(app)
                response = client.get(f"/metrics?time_range={time_range}")

                assert response.status_code == 200


class TestBulkOperations:
    """Tests for bulk operation endpoints."""

    def test_bulk_cancel_tasks(self, mock_admin_user, mock_task):
        """Test bulk cancelling tasks."""
        mock_task.stage = ProcessingStage.EMBEDDING.value

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        client = TestClient(app)
        response = client.post(
            "/tasks/bulk/cancel",
            json={"task_ids": ["task-1", "task-2"], "reason": "Batch cleanup"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "cancelled" in data
        assert "failed" in data

    def test_bulk_retry_tasks(self, mock_admin_user, mock_failed_task):
        """Test bulk retrying tasks."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db()
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'retry_task', new=AsyncMock()) as mock_retry:
            mock_retry.return_value = mock_failed_task

            client = TestClient(app)
            response = client.post(
                "/tasks/bulk/retry",
                json={"task_ids": ["task-1", "task-2"]}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_bulk_delete_tasks(self, mock_admin_user, mock_task):
        """Test bulk deleting tasks."""
        mock_task.status = ProcessingStatus.COMPLETED.value

        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db(mock_task=mock_task)
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'delete_task', new=AsyncMock()) as mock_delete:
            mock_delete.return_value = True

            client = TestClient(app)
            response = client.post(
                "/tasks/bulk/delete",
                json={"task_ids": ["task-1", "task-2"]}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True


class TestCleanupOldTasks:
    """Tests for POST /cleanup endpoint."""

    def test_cleanup_old_tasks(self, mock_admin_user):
        """Test cleaning up old tasks."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db()
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'delete_old_tasks', new=AsyncMock()) as mock_cleanup:
            mock_cleanup.return_value = 25

            client = TestClient(app)
            response = client.post("/cleanup?days=30")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["deleted_count"] == 25
            assert data["older_than_days"] == 30

    def test_cleanup_with_status_filter(self, mock_admin_user):
        """Test cleanup with status filter."""
        global _current_admin, _current_db
        _current_admin = mock_admin_user
        mock_db = _make_async_db()
        _current_db = mock_db

        with patch.object(ProcessingTasks, 'delete_old_tasks', new=AsyncMock()) as mock_cleanup:
            mock_cleanup.return_value = 15

            client = TestClient(app)
            response = client.post("/cleanup?days=7&status=failed")

            assert response.status_code == 200
            data = response.json()
            assert data["deleted_count"] == 15
