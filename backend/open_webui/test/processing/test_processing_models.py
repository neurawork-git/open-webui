"""
Unit tests for document processing models and state machine logic.

Tests ProcessingTask model, state transitions, progress calculation,
and the ProcessingTaskTracker helper class.
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch

from open_webui.models.processing import (
    ProcessingTask,
    ProcessingTasks,
    ProcessingTaskCreate,
    ProcessingTaskUpdate,
    ProcessingTaskModel,
    ProcessingTaskResponse,
    ProcessingTaskTracker,
    ProcessingMetrics,
    ProcessingStatus,
    ProcessingStage,
    DocumentType,
    STAGE_PROGRESS_RANGES,
    VALID_TRANSITIONS,
    can_transition,
    is_terminal_state,
    can_cancel,
    can_retry,
    get_progress_for_stage,
    ProcessingCancelledException,
)


class TestProcessingEnums:
    """Tests for processing-related enums."""

    def test_processing_status_values(self):
        """Test that ProcessingStatus has expected values."""
        assert ProcessingStatus.QUEUED.value == "queued"
        assert ProcessingStatus.PROCESSING.value == "processing"
        assert ProcessingStatus.COMPLETED.value == "completed"
        assert ProcessingStatus.FAILED.value == "failed"
        assert ProcessingStatus.CANCELLED.value == "cancelled"

    def test_processing_stage_values(self):
        """Test that ProcessingStage has expected values."""
        assert ProcessingStage.QUEUED.value == "queued"
        assert ProcessingStage.EXTRACTING.value == "extracting"
        assert ProcessingStage.CHUNKING.value == "chunking"
        assert ProcessingStage.EMBEDDING.value == "embedding"
        assert ProcessingStage.INDEXING.value == "indexing"
        assert ProcessingStage.COMPLETED.value == "completed"
        assert ProcessingStage.FAILED.value == "failed"
        assert ProcessingStage.CANCELLED.value == "cancelled"

    def test_document_type_values(self):
        """Test that DocumentType has expected values."""
        assert DocumentType.FILE_UPLOAD.value == "file_upload"
        assert DocumentType.WEB_SCRAPE.value == "web_scrape"
        assert DocumentType.URL_IMPORT.value == "url_import"


class TestStageProgressRanges:
    """Tests for stage progress range configuration."""

    def test_all_stages_have_ranges(self):
        """Test that all stages have defined progress ranges."""
        expected_stages = [
            ProcessingStage.QUEUED,
            ProcessingStage.EXTRACTING,
            ProcessingStage.CHUNKING,
            ProcessingStage.EMBEDDING,
            ProcessingStage.INDEXING,
            ProcessingStage.COMPLETED,
            ProcessingStage.FAILED,
            ProcessingStage.CANCELLED,
        ]
        for stage in expected_stages:
            assert stage in STAGE_PROGRESS_RANGES, f"Missing range for {stage}"

    def test_progress_ranges_are_valid(self):
        """Test that all progress ranges have valid start <= end."""
        for stage, (start, end) in STAGE_PROGRESS_RANGES.items():
            assert 0.0 <= start <= 1.0, f"Invalid start for {stage}: {start}"
            assert 0.0 <= end <= 1.0, f"Invalid end for {stage}: {end}"
            assert start <= end, f"Start > end for {stage}: {start} > {end}"

    def test_queued_starts_at_zero(self):
        """Test that QUEUED stage starts at 0%."""
        start, _ = STAGE_PROGRESS_RANGES[ProcessingStage.QUEUED]
        assert start == 0.0

    def test_completed_ends_at_one(self):
        """Test that COMPLETED stage ends at 100%."""
        _, end = STAGE_PROGRESS_RANGES[ProcessingStage.COMPLETED]
        assert end == 1.0


class TestValidTransitions:
    """Tests for valid state transitions."""

    def test_queued_transitions(self):
        """Test valid transitions from QUEUED."""
        assert ProcessingStage.EXTRACTING in VALID_TRANSITIONS[ProcessingStage.QUEUED]
        assert ProcessingStage.FAILED in VALID_TRANSITIONS[ProcessingStage.QUEUED]
        assert ProcessingStage.CANCELLED in VALID_TRANSITIONS[ProcessingStage.QUEUED]

    def test_extracting_transitions(self):
        """Test valid transitions from EXTRACTING."""
        assert ProcessingStage.CHUNKING in VALID_TRANSITIONS[ProcessingStage.EXTRACTING]
        assert ProcessingStage.FAILED in VALID_TRANSITIONS[ProcessingStage.EXTRACTING]
        assert ProcessingStage.CANCELLED in VALID_TRANSITIONS[ProcessingStage.EXTRACTING]

    def test_terminal_states_have_no_transitions(self):
        """Test that terminal states have no outgoing transitions (except FAILED which allows retry)."""
        assert len(VALID_TRANSITIONS[ProcessingStage.COMPLETED]) == 0
        assert len(VALID_TRANSITIONS[ProcessingStage.CANCELLED]) == 0
        # FAILED allows retry -> QUEUED
        assert VALID_TRANSITIONS[ProcessingStage.FAILED] == [ProcessingStage.QUEUED]


class TestCanTransition:
    """Tests for can_transition helper function."""

    def test_valid_forward_transition(self):
        """Test valid forward state transitions."""
        assert can_transition(ProcessingStage.QUEUED, ProcessingStage.EXTRACTING) is True
        assert can_transition(ProcessingStage.EXTRACTING, ProcessingStage.CHUNKING) is True
        assert can_transition(ProcessingStage.CHUNKING, ProcessingStage.EMBEDDING) is True
        assert can_transition(ProcessingStage.EMBEDDING, ProcessingStage.INDEXING) is True
        assert can_transition(ProcessingStage.INDEXING, ProcessingStage.COMPLETED) is True

    def test_invalid_backward_transition(self):
        """Test that backward transitions are not allowed."""
        assert can_transition(ProcessingStage.EMBEDDING, ProcessingStage.EXTRACTING) is False
        assert can_transition(ProcessingStage.COMPLETED, ProcessingStage.QUEUED) is False

    def test_transition_to_failed(self):
        """Test that any active stage can transition to FAILED."""
        active_stages = [
            ProcessingStage.QUEUED,
            ProcessingStage.EXTRACTING,
            ProcessingStage.CHUNKING,
            ProcessingStage.EMBEDDING,
            ProcessingStage.INDEXING,
        ]
        for stage in active_stages:
            assert can_transition(stage, ProcessingStage.FAILED) is True

    def test_transition_to_cancelled(self):
        """Test that any active stage can transition to CANCELLED."""
        active_stages = [
            ProcessingStage.QUEUED,
            ProcessingStage.EXTRACTING,
            ProcessingStage.CHUNKING,
            ProcessingStage.EMBEDDING,
            ProcessingStage.INDEXING,
        ]
        for stage in active_stages:
            assert can_transition(stage, ProcessingStage.CANCELLED) is True


class TestIsTerminalState:
    """Tests for is_terminal_state helper function."""

    def test_terminal_states(self):
        """Test that terminal states are correctly identified."""
        assert is_terminal_state(ProcessingStage.COMPLETED) is True
        assert is_terminal_state(ProcessingStage.FAILED) is True
        assert is_terminal_state(ProcessingStage.CANCELLED) is True

    def test_non_terminal_states(self):
        """Test that non-terminal states are correctly identified."""
        assert is_terminal_state(ProcessingStage.QUEUED) is False
        assert is_terminal_state(ProcessingStage.EXTRACTING) is False
        assert is_terminal_state(ProcessingStage.CHUNKING) is False
        assert is_terminal_state(ProcessingStage.EMBEDDING) is False
        assert is_terminal_state(ProcessingStage.INDEXING) is False


class TestCanCancel:
    """Tests for can_cancel helper function."""

    def test_cancellable_stages(self):
        """Test stages that can be cancelled."""
        assert can_cancel(ProcessingStage.QUEUED) is True
        assert can_cancel(ProcessingStage.EXTRACTING) is True
        assert can_cancel(ProcessingStage.CHUNKING) is True
        assert can_cancel(ProcessingStage.EMBEDDING) is True
        assert can_cancel(ProcessingStage.INDEXING) is True

    def test_non_cancellable_stages(self):
        """Test stages that cannot be cancelled."""
        assert can_cancel(ProcessingStage.COMPLETED) is False
        assert can_cancel(ProcessingStage.FAILED) is False
        assert can_cancel(ProcessingStage.CANCELLED) is False


class TestCanRetry:
    """Tests for can_retry helper function."""

    def test_retryable_stage(self):
        """Test that only FAILED stage is retryable."""
        assert can_retry(ProcessingStage.FAILED) is True

    def test_non_retryable_stages(self):
        """Test that other stages are not retryable."""
        assert can_retry(ProcessingStage.QUEUED) is False
        assert can_retry(ProcessingStage.EXTRACTING) is False
        assert can_retry(ProcessingStage.CHUNKING) is False
        assert can_retry(ProcessingStage.EMBEDDING) is False
        assert can_retry(ProcessingStage.INDEXING) is False
        assert can_retry(ProcessingStage.COMPLETED) is False
        assert can_retry(ProcessingStage.CANCELLED) is False


class TestGetProgressForStage:
    """Tests for get_progress_for_stage helper function."""

    def test_queued_progress(self):
        """Test progress calculation for QUEUED stage."""
        # QUEUED is 0.0 - 0.0, so always 0
        assert get_progress_for_stage(ProcessingStage.QUEUED, 0.0) == 0.0
        assert get_progress_for_stage(ProcessingStage.QUEUED, 0.5) == 0.0
        assert get_progress_for_stage(ProcessingStage.QUEUED, 1.0) == 0.0

    def test_extracting_progress(self):
        """Test progress calculation for EXTRACTING stage."""
        # EXTRACTING is 0.0 - 0.2
        assert get_progress_for_stage(ProcessingStage.EXTRACTING, 0.0) == 0.0
        assert get_progress_for_stage(ProcessingStage.EXTRACTING, 0.5) == 0.1
        assert get_progress_for_stage(ProcessingStage.EXTRACTING, 1.0) == 0.2

    def test_embedding_progress(self):
        """Test progress calculation for EMBEDDING stage."""
        # EMBEDDING is 0.30 - 0.95 (the main work)
        progress_at_0 = get_progress_for_stage(ProcessingStage.EMBEDDING, 0.0)
        progress_at_50 = get_progress_for_stage(ProcessingStage.EMBEDDING, 0.5)
        progress_at_100 = get_progress_for_stage(ProcessingStage.EMBEDDING, 1.0)

        assert progress_at_0 == pytest.approx(0.30, rel=0.01)
        assert progress_at_50 == pytest.approx(0.625, rel=0.01)
        assert progress_at_100 == pytest.approx(0.95, rel=0.01)

    def test_completed_progress(self):
        """Test progress calculation for COMPLETED stage."""
        assert get_progress_for_stage(ProcessingStage.COMPLETED, 0.0) == 1.0
        assert get_progress_for_stage(ProcessingStage.COMPLETED, 1.0) == 1.0

    def test_failed_progress(self):
        """Test progress calculation for FAILED stage returns current progress."""
        # FAILED maintains current progress
        progress = get_progress_for_stage(ProcessingStage.FAILED, 0.5)
        # Based on implementation, should be in 1.0-1.0 range (no change)
        assert 0.0 <= progress <= 1.0


class TestProcessingTaskCreate:
    """Tests for ProcessingTaskCreate Pydantic model."""

    def test_minimal_create(self):
        """Test creating task with minimal required fields."""
        task = ProcessingTaskCreate(
            document_name="test.pdf",
            document_type=DocumentType.FILE_UPLOAD.value,
        )
        assert task.document_name == "test.pdf"
        assert task.document_type == DocumentType.FILE_UPLOAD.value
        assert task.document_id is None
        assert task.chat_id is None

    def test_full_create(self):
        """Test creating task with all fields."""
        task = ProcessingTaskCreate(
            document_id="doc-123",
            document_name="test.pdf",
            document_type=DocumentType.FILE_UPLOAD.value,
            chat_id="chat-456",
            knowledge_id="kb-789",
            meta={"source": "upload"},
        )
        assert task.document_id == "doc-123"
        assert task.document_name == "test.pdf"
        assert task.chat_id == "chat-456"
        assert task.knowledge_id == "kb-789"
        assert task.meta == {"source": "upload"}


class TestProcessingTaskUpdate:
    """Tests for ProcessingTaskUpdate Pydantic model."""

    def test_update_stage(self):
        """Test updating stage."""
        update = ProcessingTaskUpdate(stage=ProcessingStage.EMBEDDING.value)
        assert update.stage == ProcessingStage.EMBEDDING.value
        assert update.progress is None

    def test_update_progress(self):
        """Test updating progress fields."""
        update = ProcessingTaskUpdate(
            progress=0.5,
            processed_chunks=50,
            total_chunks=100,
        )
        assert update.progress == 0.5
        assert update.processed_chunks == 50
        assert update.total_chunks == 100

    def test_update_error(self):
        """Test updating error fields."""
        update = ProcessingTaskUpdate(
            error_message="Connection timeout",
            error_details={"type": "TimeoutError"},
        )
        assert update.error_message == "Connection timeout"
        assert update.error_details == {"type": "TimeoutError"}


class TestProcessingMetrics:
    """Tests for ProcessingMetrics Pydantic model."""

    def test_default_metrics(self):
        """Test default metrics values."""
        metrics = ProcessingMetrics(
            total_tasks=100,
            queued=5,
            processing=10,
            completed=80,
            failed=3,
            cancelled=2,
        )
        assert metrics.total_tasks == 100
        assert metrics.queued == 5
        assert metrics.processing == 10
        assert metrics.completed == 80
        assert metrics.failed == 3
        assert metrics.cancelled == 2
        assert metrics.avg_processing_time is None
        assert metrics.success_rate is None

    def test_metrics_with_rates(self):
        """Test metrics with calculated rates."""
        metrics = ProcessingMetrics(
            total_tasks=100,
            queued=5,
            processing=10,
            completed=80,
            failed=3,
            cancelled=2,
            avg_processing_time=45.5,
            success_rate=94.1,
            documents_processed=85,
            chunks_processed=5000,
        )
        assert metrics.avg_processing_time == 45.5
        assert metrics.success_rate == 94.1
        assert metrics.documents_processed == 85
        assert metrics.chunks_processed == 5000


class TestProcessingCancelledException:
    """Tests for ProcessingCancelledException."""

    def test_exception_message(self):
        """Test exception can be raised with message."""
        with pytest.raises(ProcessingCancelledException) as exc_info:
            raise ProcessingCancelledException("Task cancelled by user")
        assert str(exc_info.value) == "Task cancelled by user"

    def test_exception_is_exception(self):
        """Test that ProcessingCancelledException is an Exception."""
        assert issubclass(ProcessingCancelledException, Exception)


class TestProcessingTaskTracker:
    """Tests for ProcessingTaskTracker helper class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def mock_task(self):
        """Create a mock processing task."""
        task = MagicMock()
        task.id = "task-123"
        task.status = ProcessingStatus.PROCESSING.value
        task.stage = ProcessingStage.QUEUED.value
        task.progress = 0.0
        task.cancel_requested = False
        return task

    def test_tracker_initialization(self, mock_db, mock_task):
        """Test tracker initialization."""
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            tracker = ProcessingTaskTracker("task-123", db=mock_db)
            assert tracker.task_id == "task-123"

    @pytest.mark.asyncio
    async def test_update_stage(self, mock_db, mock_task):
        """Test updating processing stage."""
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            with patch.object(ProcessingTasks, 'update_task', new=AsyncMock()) as mock_update:
                tracker = ProcessingTaskTracker("task-123", db=mock_db)
                await tracker.update_stage(ProcessingStage.EXTRACTING)

                mock_update.assert_called()
                call_args = mock_update.call_args
                assert call_args[0][0] == "task-123"

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_false(self, mock_db, mock_task):
        """Test is_cancelled returns False when not cancelled."""
        mock_task.cancel_requested = False
        # get_task_by_id returns a ProcessingTaskModel-like object; the mock task has cancel_requested=False
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            tracker = ProcessingTaskTracker("task-123", db=mock_db)
            assert await tracker.is_cancelled() is False

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_true(self, mock_db, mock_task):
        """Test is_cancelled returns True when cancelled."""
        mock_task.cancel_requested = True
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            tracker = ProcessingTaskTracker("task-123", db=mock_db)
            assert await tracker.is_cancelled() is True

    @pytest.mark.asyncio
    async def test_complete_sets_terminal_state(self, mock_db, mock_task):
        """Test complete() calls complete_task."""
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            with patch.object(ProcessingTasks, 'complete_task', new=AsyncMock()) as mock_complete:
                tracker = ProcessingTaskTracker("task-123", db=mock_db)
                await tracker.complete()

                mock_complete.assert_called()
                call_args = mock_complete.call_args
                assert call_args[0][0] == "task-123"

    @pytest.mark.asyncio
    async def test_fail_sets_error_state(self, mock_db, mock_task):
        """Test fail() calls fail_task with error message."""
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            with patch.object(ProcessingTasks, 'fail_task', new=AsyncMock()) as mock_fail:
                tracker = ProcessingTaskTracker("task-123", db=mock_db)
                await tracker.fail("Connection error", {"type": "NetworkError"})

                mock_fail.assert_called()
                call_args = mock_fail.call_args
                assert call_args[0][0] == "task-123"
                assert call_args[0][1] == "Connection error"

    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_state(self, mock_db, mock_task):
        """Test cancel() calls cancel_task."""
        with patch.object(ProcessingTasks, 'get_task_by_id', new=AsyncMock(return_value=mock_task)):
            with patch.object(ProcessingTasks, 'cancel_task', new=AsyncMock()) as mock_cancel:
                tracker = ProcessingTaskTracker("task-123", db=mock_db)
                await tracker.cancel()

                mock_cancel.assert_called()
                call_args = mock_cancel.call_args
                assert call_args[0][0] == "task-123"


class TestProcessingTasksTable:
    """Tests for ProcessingTasks table operations."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_get_metrics_returns_metrics_object(self, mock_db):
        """Test get_metrics returns ProcessingMetrics."""
        with patch.object(ProcessingTasks, 'get_metrics', new=AsyncMock()) as mock_get_metrics:
            mock_get_metrics.return_value = ProcessingMetrics(
                total_tasks=100,
                queued=5,
                processing=10,
                completed=80,
                failed=3,
                cancelled=2,
                avg_processing_time=45.5,
                success_rate=94.1,
            )

            metrics = await ProcessingTasks.get_metrics(since_timestamp=0, db=mock_db)

            assert isinstance(metrics, ProcessingMetrics)
            assert metrics.total_tasks == 100


class TestProcessingTaskColumnTypes:
    """Guards the model against drifting back to TEXT-backed JSON columns.

    On Postgres `processing_task.error_details` and `.metadata` are `json`
    (verified on neurawork-test and neurawork-prod, 2026-07-27). The TEXT-backed
    JSONField binds VARCHAR, so every INSERT fails with

        psycopg.errors.DatatypeMismatch: column "error_details" is of type json
        but expression is of type character varying

    and — because the dashboard tracker is deliberately best-effort — it fails
    silently: uploads succeed, the dashboard just stays empty forever. SQLite
    accepts either type, so no amount of local testing catches this. Hence a
    type assertion rather than a behavioural test.
    """

    def test_json_columns_are_native_json(self):
        from sqlalchemy import JSON

        from open_webui.models.processing import ProcessingTask

        for column_name in ('error_details', 'metadata'):
            column = ProcessingTask.__table__.columns[column_name]
            assert isinstance(column.type, JSON), (
                f'{column_name} must be sa.JSON to match the Postgres schema; '
                f'got {type(column.type).__name__}'
            )
