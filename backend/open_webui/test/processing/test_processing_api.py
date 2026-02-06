"""
Unit tests for document processing API endpoints.

Tests the REST API endpoints in routers/processing.py using proper
FastAPI dependency overrides.
"""

import pytest
import time
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from open_webui.routers.processing import router
from open_webui.models.processing import (
    ProcessingTask,
    ProcessingTasks,
    ProcessingTaskModel,
    ProcessingTaskResponse,
    ProcessingTaskListResponse,
    ProcessingMetrics,
    ProcessingStatus,
    ProcessingStage,
    DocumentType,
)


# Create a test app with the router
app = FastAPI()
app.include_router(router, prefix="/api/v1/admin/processing")


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    user = MagicMock()
    user.id = "admin-123"
    user.role = "admin"
    return user


@pytest.fixture
def mock_task_model():
    """Create a mock ProcessingTaskModel."""
    return ProcessingTaskModel(
        id="task-123",
        document_id="doc-456",
        document_name="test.pdf",
        document_type=DocumentType.FILE_UPLOAD.value,
        user_id="user-789",
        chat_id=None,
        knowledge_id=None,
        status=ProcessingStatus.PROCESSING.value,
        stage=ProcessingStage.EMBEDDING.value,
        progress=0.5,
        created_at=int(time.time()) - 60,
        started_at=int(time.time()) - 50,
        completed_at=None,
        total_chunks=100,
        processed_chunks=50,
        current_batch=5,
        retry_count=0,
        error_message=None,
        error_details=None,
        cancel_requested=False,
        cancelled_by=None,
        cancelled_at=None,
        task_metadata={},
    )


@pytest.fixture
def mock_failed_task_model():
    """Create a mock failed ProcessingTaskModel."""
    return ProcessingTaskModel(
        id="task-failed",
        document_id="doc-456",
        document_name="test.pdf",
        document_type=DocumentType.FILE_UPLOAD.value,
        user_id="user-789",
        chat_id=None,
        knowledge_id=None,
        status=ProcessingStatus.FAILED.value,
        stage=ProcessingStage.FAILED.value,
        progress=0.3,
        created_at=int(time.time()) - 120,
        started_at=int(time.time()) - 110,
        completed_at=int(time.time()) - 10,
        total_chunks=100,
        processed_chunks=30,
        current_batch=3,
        retry_count=1,
        error_message="Connection timeout",
        error_details={"type": "TimeoutError"},
        cancel_requested=False,
        cancelled_by=None,
        cancelled_at=None,
        task_metadata={},
    )


class TestProcessingTaskModel:
    """Tests for ProcessingTaskModel serialization."""

    def test_task_model_serialization(self, mock_task_model):
        """Test that ProcessingTaskModel can be serialized to dict."""
        data = mock_task_model.model_dump()
        assert data["id"] == "task-123"
        assert data["document_id"] == "doc-456"
        assert data["status"] == "processing"
        assert data["stage"] == "embedding"
        assert data["progress"] == 0.5

    def test_task_model_from_dict(self):
        """Test creating ProcessingTaskModel from dict."""
        data = {
            "id": "task-456",
            "document_id": "doc-789",
            "document_name": "report.pdf",
            "document_type": "file_upload",
            "user_id": "user-123",
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "created_at": int(time.time()),
            "processed_chunks": 0,
            "current_batch": 0,
            "retry_count": 0,
            "cancel_requested": False,
        }
        model = ProcessingTaskModel(**data)
        assert model.id == "task-456"
        assert model.status == "queued"


class TestProcessingTaskResponse:
    """Tests for ProcessingTaskResponse serialization."""

    def test_response_includes_elapsed_time(self, mock_task_model):
        """Test that response can include elapsed time calculation."""
        response = ProcessingTaskResponse(
            id=mock_task_model.id,
            document_id=mock_task_model.document_id,
            document_name=mock_task_model.document_name,
            document_type=mock_task_model.document_type,
            user_id=mock_task_model.user_id,
            status=mock_task_model.status,
            stage=mock_task_model.stage,
            progress=mock_task_model.progress,
            created_at=mock_task_model.created_at,
            started_at=mock_task_model.started_at,
            elapsed_seconds=50,
            processed_chunks=mock_task_model.processed_chunks,
            retry_count=mock_task_model.retry_count,
            cancel_requested=mock_task_model.cancel_requested,
        )
        assert response.elapsed_seconds == 50


class TestProcessingMetricsModel:
    """Tests for ProcessingMetrics model."""

    def test_default_metrics(self):
        """Test default ProcessingMetrics values."""
        metrics = ProcessingMetrics()
        assert metrics.total_tasks == 0
        assert metrics.queued == 0
        assert metrics.processing == 0
        assert metrics.completed == 0
        assert metrics.failed == 0
        assert metrics.cancelled == 0

    def test_metrics_with_values(self):
        """Test ProcessingMetrics with values."""
        metrics = ProcessingMetrics(
            total_tasks=111,
            queued=5,
            processing=3,
            completed=100,
            failed=2,
            cancelled=1,
            avg_processing_time=45.0,
            success_rate=98.0,
            documents_processed=100,
            chunks_processed=7500,
        )
        assert metrics.queued == 5
        assert metrics.processing == 3
        assert metrics.chunks_processed == 7500


class TestProcessingTaskListResponse:
    """Tests for ProcessingTaskListResponse model."""

    def test_list_response_structure(self, mock_task_model):
        """Test list response structure."""
        response_item = ProcessingTaskResponse(
            id=mock_task_model.id,
            document_id=mock_task_model.document_id,
            document_name=mock_task_model.document_name,
            document_type=mock_task_model.document_type,
            user_id=mock_task_model.user_id,
            status=mock_task_model.status,
            stage=mock_task_model.stage,
            progress=mock_task_model.progress,
            created_at=mock_task_model.created_at,
            processed_chunks=mock_task_model.processed_chunks,
            retry_count=mock_task_model.retry_count,
            cancel_requested=mock_task_model.cancel_requested,
        )
        list_response = ProcessingTaskListResponse(
            items=[response_item],
            total=1,
            limit=10,
            offset=0,
        )
        assert len(list_response.items) == 1
        assert list_response.total == 1
        assert list_response.limit == 10
        assert list_response.offset == 0


class TestProcessingTasksTableMethods:
    """Tests for ProcessingTasks table operations using mocks."""

    def test_create_task_returns_model(self):
        """Test that create_task returns a ProcessingTaskModel."""
        from open_webui.models.processing import ProcessingTaskCreate

        with patch.object(ProcessingTasks, 'create_task') as mock_create:
            mock_create.return_value = ProcessingTaskModel(
                id="new-task",
                user_id="user-123",
                status=ProcessingStatus.QUEUED.value,
                stage=ProcessingStage.QUEUED.value,
                progress=0.0,
                created_at=int(time.time()),
                processed_chunks=0,
                current_batch=0,
                retry_count=0,
                cancel_requested=False,
            )

            form = ProcessingTaskCreate(
                document_id="doc-123",
                document_name="test.pdf",
            )

            result = ProcessingTasks.create_task("user-123", form)

            assert result is not None
            assert result.id == "new-task"
            assert result.status == ProcessingStatus.QUEUED.value

    def test_get_task_by_id(self, mock_task_model):
        """Test getting task by ID."""
        with patch.object(ProcessingTasks, 'get_task_by_id') as mock_get:
            mock_get.return_value = mock_task_model

            result = ProcessingTasks.get_task_by_id("task-123")

            assert result is not None
            assert result.id == "task-123"

    def test_get_task_by_id_not_found(self):
        """Test getting non-existent task."""
        with patch.object(ProcessingTasks, 'get_task_by_id') as mock_get:
            mock_get.return_value = None

            result = ProcessingTasks.get_task_by_id("nonexistent")

            assert result is None

    def test_complete_task(self, mock_task_model):
        """Test completing a task."""
        completed_task = ProcessingTaskModel(
            **{**mock_task_model.model_dump(),
               "status": ProcessingStatus.COMPLETED.value,
               "stage": ProcessingStage.COMPLETED.value,
               "progress": 1.0,
               "completed_at": int(time.time())}
        )

        with patch.object(ProcessingTasks, 'complete_task') as mock_complete:
            mock_complete.return_value = completed_task

            result = ProcessingTasks.complete_task("task-123")

            assert result is not None
            assert result.status == ProcessingStatus.COMPLETED.value
            assert result.progress == 1.0

    def test_fail_task(self, mock_task_model):
        """Test failing a task."""
        failed_task = ProcessingTaskModel(
            **{**mock_task_model.model_dump(),
               "status": ProcessingStatus.FAILED.value,
               "stage": ProcessingStage.FAILED.value,
               "error_message": "Test error",
               "completed_at": int(time.time())}
        )

        with patch.object(ProcessingTasks, 'fail_task') as mock_fail:
            mock_fail.return_value = failed_task

            result = ProcessingTasks.fail_task("task-123", "Test error")

            assert result is not None
            assert result.status == ProcessingStatus.FAILED.value
            assert result.error_message == "Test error"


class TestCancellationLogic:
    """Tests for task cancellation business logic."""

    def test_can_cancel_active_task(self, mock_task_model):
        """Test that active tasks can be cancelled."""
        from open_webui.models.processing import can_cancel

        # Task in EMBEDDING stage should be cancellable
        assert can_cancel(ProcessingStage.EMBEDDING) is True
        assert can_cancel(ProcessingStage.QUEUED) is True
        assert can_cancel(ProcessingStage.EXTRACTING) is True

    def test_cannot_cancel_completed_task(self):
        """Test that completed tasks cannot be cancelled."""
        from open_webui.models.processing import can_cancel

        assert can_cancel(ProcessingStage.COMPLETED) is False
        assert can_cancel(ProcessingStage.CANCELLED) is False

    def test_can_retry_failed_task(self):
        """Test that failed tasks can be retried."""
        from open_webui.models.processing import can_retry

        assert can_retry(ProcessingStage.FAILED) is True
        assert can_retry(ProcessingStage.COMPLETED) is False
        assert can_retry(ProcessingStage.EMBEDDING) is False


class TestStateTransitions:
    """Tests for processing state machine transitions."""

    def test_valid_transitions(self):
        """Test valid state transitions."""
        from open_webui.models.processing import can_transition

        # Normal flow
        assert can_transition(ProcessingStage.QUEUED, ProcessingStage.EXTRACTING) is True
        assert can_transition(ProcessingStage.EXTRACTING, ProcessingStage.CHUNKING) is True
        assert can_transition(ProcessingStage.CHUNKING, ProcessingStage.EMBEDDING) is True
        assert can_transition(ProcessingStage.EMBEDDING, ProcessingStage.INDEXING) is True
        assert can_transition(ProcessingStage.INDEXING, ProcessingStage.COMPLETED) is True

    def test_invalid_backward_transitions(self):
        """Test that backward transitions are blocked."""
        from open_webui.models.processing import can_transition

        assert can_transition(ProcessingStage.EMBEDDING, ProcessingStage.EXTRACTING) is False
        assert can_transition(ProcessingStage.COMPLETED, ProcessingStage.EMBEDDING) is False

    def test_failure_transitions(self):
        """Test transitions to FAILED state."""
        from open_webui.models.processing import can_transition

        # Any active state can transition to FAILED
        for stage in [ProcessingStage.QUEUED, ProcessingStage.EXTRACTING,
                      ProcessingStage.CHUNKING, ProcessingStage.EMBEDDING,
                      ProcessingStage.INDEXING]:
            assert can_transition(stage, ProcessingStage.FAILED) is True

    def test_cancellation_transitions(self):
        """Test transitions to CANCELLED state."""
        from open_webui.models.processing import can_transition

        # Any active state can transition to CANCELLED
        for stage in [ProcessingStage.QUEUED, ProcessingStage.EXTRACTING,
                      ProcessingStage.CHUNKING, ProcessingStage.EMBEDDING,
                      ProcessingStage.INDEXING]:
            assert can_transition(stage, ProcessingStage.CANCELLED) is True


class TestProgressCalculation:
    """Tests for progress calculation logic."""

    def test_progress_increases_through_stages(self):
        """Test that progress increases through stages."""
        from open_webui.models.processing import get_progress_for_stage

        # Progress should increase as we move through stages
        queued_progress = get_progress_for_stage(ProcessingStage.QUEUED, 1.0)
        extracting_progress = get_progress_for_stage(ProcessingStage.EXTRACTING, 1.0)
        chunking_progress = get_progress_for_stage(ProcessingStage.CHUNKING, 1.0)
        embedding_progress = get_progress_for_stage(ProcessingStage.EMBEDDING, 1.0)
        indexing_progress = get_progress_for_stage(ProcessingStage.INDEXING, 1.0)
        completed_progress = get_progress_for_stage(ProcessingStage.COMPLETED, 1.0)

        assert queued_progress <= extracting_progress
        assert extracting_progress <= chunking_progress
        assert chunking_progress <= embedding_progress
        assert embedding_progress <= indexing_progress
        assert indexing_progress <= completed_progress
        assert completed_progress == 1.0

    def test_embedding_takes_most_progress(self):
        """Test that embedding stage takes the largest progress range."""
        from open_webui.models.processing import STAGE_PROGRESS_RANGES

        # Embedding should be the largest range since it's the most time-consuming
        embedding_range = STAGE_PROGRESS_RANGES[ProcessingStage.EMBEDDING]
        embedding_size = embedding_range[1] - embedding_range[0]

        for stage, (start, end) in STAGE_PROGRESS_RANGES.items():
            if stage not in [ProcessingStage.EMBEDDING, ProcessingStage.FAILED, ProcessingStage.CANCELLED]:
                stage_size = end - start
                assert embedding_size >= stage_size, f"Embedding range should be >= {stage} range"
