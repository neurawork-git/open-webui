"""
Processing Task Model for Document Processing Dashboard.

Tracks the state and progress of document processing operations including
file uploads, embeddings, and web scraping.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Float, Integer, String, Text, select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.internal.db import Base, JSONField, get_async_db_context

log = logging.getLogger(__name__)


####################
# Enums
####################


class ProcessingStatus(str, Enum):
    """Overall status of a processing task."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingStage(str, Enum):
    """Current processing stage with associated progress ranges.

    Progress ranges:
    - QUEUED: 0%
    - EXTRACTING: 0-20%
    - CHUNKING: 20-30%
    - EMBEDDING: 30-95%
    - INDEXING: 95-100%
    - COMPLETED: 100%
    """
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocumentType(str, Enum):
    """Type of document being processed."""
    FILE_UPLOAD = "file_upload"
    WEB_SCRAPE = "web_scrape"
    URL_IMPORT = "url_import"


# Progress range definitions for each stage
STAGE_PROGRESS_RANGES = {
    ProcessingStage.QUEUED: (0.0, 0.0),
    ProcessingStage.EXTRACTING: (0.0, 0.20),
    ProcessingStage.CHUNKING: (0.20, 0.30),
    ProcessingStage.EMBEDDING: (0.30, 0.95),
    ProcessingStage.INDEXING: (0.95, 1.0),
    ProcessingStage.COMPLETED: (1.0, 1.0),
    ProcessingStage.FAILED: (0.0, 1.0),  # Can fail at any point
    ProcessingStage.CANCELLED: (0.0, 1.0),  # Can cancel at any point
}

# Valid state transitions
VALID_TRANSITIONS = {
    ProcessingStage.QUEUED: [ProcessingStage.EXTRACTING, ProcessingStage.FAILED, ProcessingStage.CANCELLED],
    ProcessingStage.EXTRACTING: [ProcessingStage.CHUNKING, ProcessingStage.FAILED, ProcessingStage.CANCELLED],
    ProcessingStage.CHUNKING: [ProcessingStage.EMBEDDING, ProcessingStage.FAILED, ProcessingStage.CANCELLED],
    ProcessingStage.EMBEDDING: [ProcessingStage.INDEXING, ProcessingStage.FAILED, ProcessingStage.CANCELLED],
    ProcessingStage.INDEXING: [ProcessingStage.COMPLETED, ProcessingStage.FAILED, ProcessingStage.CANCELLED],
    ProcessingStage.COMPLETED: [],  # Terminal state
    ProcessingStage.FAILED: [ProcessingStage.QUEUED],  # Can retry
    ProcessingStage.CANCELLED: [],  # Terminal state
}


####################
# DB Schema
####################


class ProcessingTask(Base):
    """SQLAlchemy model for processing tasks."""
    __tablename__ = "processing_task"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Document reference
    document_id = Column(String, nullable=True)  # FK to files table
    document_name = Column(String, nullable=True)
    document_type = Column(String, default=DocumentType.FILE_UPLOAD.value)

    # User/context reference
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=True)
    knowledge_id = Column(String, nullable=True)

    # State tracking
    status = Column(String, default=ProcessingStatus.QUEUED.value)
    stage = Column(String, default=ProcessingStage.QUEUED.value)
    progress = Column(Float, default=0.0)

    # Timing
    created_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger, nullable=True)
    completed_at = Column(BigInteger, nullable=True)

    # Progress details
    total_chunks = Column(Integer, nullable=True)
    processed_chunks = Column(Integer, default=0)
    current_batch = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_details = Column(JSONField, nullable=True)

    # Cancellation
    cancel_requested = Column(Boolean, default=False)
    cancelled_by = Column(String, nullable=True)
    cancelled_at = Column(BigInteger, nullable=True)

    # Additional metadata (scraper type, URL, content size, etc.)
    # NOTE: attribute is 'meta' (DB column stays 'metadata') because 'metadata'
    # is reserved by SQLAlchemy's Declarative Base.
    meta = Column("metadata", JSONField, nullable=True)


####################
# Pydantic Models
####################


class ProcessingTaskModel(BaseModel):
    """Pydantic model for ProcessingTask."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_type: str = DocumentType.FILE_UPLOAD.value

    user_id: str
    chat_id: Optional[str] = None
    knowledge_id: Optional[str] = None

    status: str = ProcessingStatus.QUEUED.value
    stage: str = ProcessingStage.QUEUED.value
    progress: float = 0.0

    created_at: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None

    total_chunks: Optional[int] = None
    processed_chunks: int = 0
    current_batch: int = 0
    retry_count: int = 0

    error_message: Optional[str] = None
    error_details: Optional[dict] = None

    cancel_requested: bool = False
    cancelled_by: Optional[str] = None
    cancelled_at: Optional[int] = None

    meta: Optional[dict] = None


class ProcessingTaskResponse(BaseModel):
    """Response model for API endpoints."""
    id: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_type: str

    user_id: str
    chat_id: Optional[str] = None

    status: str
    stage: str
    progress: float

    created_at: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    elapsed_seconds: Optional[int] = None

    total_chunks: Optional[int] = None
    processed_chunks: int = 0
    retry_count: int = 0

    error_message: Optional[str] = None

    cancel_requested: bool = False

    model_config = ConfigDict(from_attributes=True)


class ProcessingTaskCreate(BaseModel):
    """Form for creating a new processing task."""
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_type: str = DocumentType.FILE_UPLOAD.value
    chat_id: Optional[str] = None
    knowledge_id: Optional[str] = None
    meta: Optional[dict] = None


class ProcessingTaskUpdate(BaseModel):
    """Form for updating a processing task."""
    stage: Optional[str] = None
    progress: Optional[float] = None
    total_chunks: Optional[int] = None
    processed_chunks: Optional[int] = None
    current_batch: Optional[int] = None
    error_message: Optional[str] = None
    error_details: Optional[dict] = None
    meta: Optional[dict] = None


class ProcessingMetrics(BaseModel):
    """Aggregate metrics for the processing dashboard."""
    # Counts by status (matches frontend expectations)
    total_tasks: int = 0
    queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0

    # Performance metrics
    avg_processing_time: Optional[float] = None  # in seconds
    success_rate: Optional[float] = None  # percentage 0-100

    # Volume metrics
    documents_processed: int = 0
    chunks_processed: int = 0


class ProcessingTaskListResponse(BaseModel):
    """Paginated list response."""
    items: List[ProcessingTaskResponse]
    total: int
    limit: int
    offset: int


####################
# Helper Functions
####################


def can_transition(from_stage: ProcessingStage, to_stage: ProcessingStage) -> bool:
    """Check if a state transition is valid."""
    return to_stage in VALID_TRANSITIONS.get(from_stage, [])


def is_terminal_state(stage: ProcessingStage) -> bool:
    """Check if a stage is a terminal state (no further transitions)."""
    return len(VALID_TRANSITIONS.get(stage, [])) == 0 or stage == ProcessingStage.FAILED


def can_cancel(stage: ProcessingStage) -> bool:
    """Check if a task can be cancelled from the given stage."""
    return ProcessingStage.CANCELLED in VALID_TRANSITIONS.get(stage, [])


def can_retry(stage: ProcessingStage) -> bool:
    """Check if a task can be retried from the given stage."""
    return stage == ProcessingStage.FAILED


def get_progress_for_stage(stage: ProcessingStage, stage_progress: float = 0.0) -> float:
    """
    Calculate overall progress based on stage and progress within that stage.

    Args:
        stage: Current processing stage
        stage_progress: Progress within the current stage (0.0 to 1.0)

    Returns:
        Overall progress (0.0 to 1.0)
    """
    min_progress, max_progress = STAGE_PROGRESS_RANGES.get(stage, (0.0, 1.0))
    return min_progress + (max_progress - min_progress) * stage_progress


####################
# Table Operations
####################


class ProcessingTasksTable:
    """Database operations for ProcessingTask."""

    async def create_task(
        self,
        user_id: str,
        form_data: ProcessingTaskCreate,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Create a new processing task."""
        async with get_async_db_context(db) as db:
            try:
                task_id = str(uuid.uuid4())
                now = int(time.time())

                task = ProcessingTask(
                    id=task_id,
                    user_id=user_id,
                    document_id=form_data.document_id,
                    document_name=form_data.document_name,
                    document_type=form_data.document_type,
                    chat_id=form_data.chat_id,
                    knowledge_id=form_data.knowledge_id,
                    status=ProcessingStatus.QUEUED.value,
                    stage=ProcessingStage.QUEUED.value,
                    progress=0.0,
                    created_at=now,
                    meta=form_data.meta,
                )

                db.add(task)
                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error creating processing task: {e}")
                return None

    async def get_task_by_id(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Get a processing task by ID."""
        async with get_async_db_context(db) as db:
            try:
                task = await db.get(ProcessingTask, task_id)
                if task:
                    return ProcessingTaskModel.model_validate(task)
                return None
            except Exception as e:
                log.exception(f"Error getting processing task: {e}")
                return None

    async def get_tasks(
        self,
        status: Optional[ProcessingStatus] = None,
        user_id: Optional[str] = None,
        document_type: Optional[DocumentType] = None,
        limit: int = 50,
        offset: int = 0,
        db: Optional[AsyncSession] = None
    ) -> List[ProcessingTaskModel]:
        """Get processing tasks with optional filtering."""
        async with get_async_db_context(db) as db:
            try:
                stmt = select(ProcessingTask)

                if status:
                    stmt = stmt.where(ProcessingTask.status == status.value)
                if user_id:
                    stmt = stmt.where(ProcessingTask.user_id == user_id)
                if document_type:
                    stmt = stmt.where(ProcessingTask.document_type == document_type.value)

                stmt = (
                    stmt.order_by(ProcessingTask.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )

                result = await db.execute(stmt)
                tasks = result.scalars().all()

                return [ProcessingTaskModel.model_validate(task) for task in tasks]
            except Exception as e:
                log.exception(f"Error getting processing tasks: {e}")
                return []

    async def get_active_tasks(
        self,
        db: Optional[AsyncSession] = None
    ) -> List[ProcessingTaskModel]:
        """Get all active (non-terminal) processing tasks."""
        async with get_async_db_context(db) as db:
            try:
                stmt = (
                    select(ProcessingTask)
                    .where(ProcessingTask.status.in_([
                        ProcessingStatus.QUEUED.value,
                        ProcessingStatus.PROCESSING.value
                    ]))
                    .order_by(ProcessingTask.created_at.asc())
                )
                result = await db.execute(stmt)
                tasks = result.scalars().all()
                return [ProcessingTaskModel.model_validate(task) for task in tasks]
            except Exception as e:
                log.exception(f"Error getting active tasks: {e}")
                return []

    async def count_tasks(
        self,
        status: Optional[ProcessingStatus] = None,
        since_timestamp: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> int:
        """Count tasks with optional filtering."""
        async with get_async_db_context(db) as db:
            try:
                stmt = select(func.count()).select_from(ProcessingTask)

                if status:
                    stmt = stmt.where(ProcessingTask.status == status.value)
                if since_timestamp:
                    stmt = stmt.where(ProcessingTask.created_at >= since_timestamp)

                result = await db.execute(stmt)
                return result.scalar() or 0
            except Exception as e:
                log.exception(f"Error counting tasks: {e}")
                return 0

    async def update_task(
        self,
        task_id: str,
        form_data: ProcessingTaskUpdate,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Update a processing task."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                if form_data.stage is not None:
                    task.stage = form_data.stage
                    # Update status based on stage
                    if form_data.stage in [ProcessingStage.COMPLETED.value]:
                        task.status = ProcessingStatus.COMPLETED.value
                        task.completed_at = int(time.time())
                    elif form_data.stage in [ProcessingStage.FAILED.value]:
                        task.status = ProcessingStatus.FAILED.value
                        task.completed_at = int(time.time())
                    elif form_data.stage in [ProcessingStage.CANCELLED.value]:
                        task.status = ProcessingStatus.CANCELLED.value
                        task.completed_at = int(time.time())
                    elif form_data.stage != ProcessingStage.QUEUED.value:
                        task.status = ProcessingStatus.PROCESSING.value
                        if task.started_at is None:
                            task.started_at = int(time.time())

                if form_data.progress is not None:
                    task.progress = form_data.progress
                if form_data.total_chunks is not None:
                    task.total_chunks = form_data.total_chunks
                if form_data.processed_chunks is not None:
                    task.processed_chunks = form_data.processed_chunks
                if form_data.current_batch is not None:
                    task.current_batch = form_data.current_batch
                if form_data.error_message is not None:
                    task.error_message = form_data.error_message
                if form_data.error_details is not None:
                    task.error_details = form_data.error_details
                if form_data.meta is not None:
                    task.meta = {**(task.meta or {}), **form_data.meta}

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error updating processing task: {e}")
                return None

    async def start_task(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Mark a task as started (transition to EXTRACTING)."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                task.stage = ProcessingStage.EXTRACTING.value
                task.status = ProcessingStatus.PROCESSING.value
                task.started_at = int(time.time())

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error starting task: {e}")
                return None

    async def complete_task(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Mark a task as completed."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                task.stage = ProcessingStage.COMPLETED.value
                task.status = ProcessingStatus.COMPLETED.value
                task.progress = 1.0
                task.completed_at = int(time.time())

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error completing task: {e}")
                return None

    async def fail_task(
        self,
        task_id: str,
        error_message: str,
        error_details: Optional[dict] = None,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Mark a task as failed."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                task.stage = ProcessingStage.FAILED.value
                task.status = ProcessingStatus.FAILED.value
                task.error_message = error_message
                task.error_details = error_details
                task.completed_at = int(time.time())

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error failing task: {e}")
                return None

    async def request_cancellation(
        self,
        task_id: str,
        cancelled_by: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Request cancellation of a task."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                # Check if task can be cancelled
                current_stage = ProcessingStage(task.stage)
                if not can_cancel(current_stage):
                    log.warning(f"Cannot cancel task {task_id} in stage {task.stage}")
                    return None

                task.cancel_requested = True
                task.cancelled_by = cancelled_by
                task.cancelled_at = int(time.time())

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error requesting cancellation: {e}")
                return None

    async def cancel_task(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Actually cancel a task (called after cancellation is processed)."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                task.stage = ProcessingStage.CANCELLED.value
                task.status = ProcessingStatus.CANCELLED.value
                task.completed_at = int(time.time())

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error cancelling task: {e}")
                return None

    async def retry_task(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> Optional[ProcessingTaskModel]:
        """Retry a failed task."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return None

                # Check if task can be retried
                if task.stage != ProcessingStage.FAILED.value:
                    log.warning(f"Cannot retry task {task_id} in stage {task.stage}")
                    return None

                task.stage = ProcessingStage.QUEUED.value
                task.status = ProcessingStatus.QUEUED.value
                task.progress = 0.0
                task.processed_chunks = 0
                task.current_batch = 0
                task.retry_count += 1
                task.error_message = None
                task.error_details = None
                task.started_at = None
                task.completed_at = None
                task.cancel_requested = False
                task.cancelled_by = None
                task.cancelled_at = None

                await db.commit()
                await db.refresh(task)

                return ProcessingTaskModel.model_validate(task)
            except Exception as e:
                log.exception(f"Error retrying task: {e}")
                return None

    async def delete_task(
        self,
        task_id: str,
        db: Optional[AsyncSession] = None
    ) -> bool:
        """Delete a processing task."""
        async with get_async_db_context(db) as db:
            try:
                result = await db.execute(
                    delete(ProcessingTask).where(ProcessingTask.id == task_id)
                )
                await db.commit()
                return (result.rowcount or 0) > 0
            except Exception as e:
                log.exception(f"Error deleting task: {e}")
                return False

    async def delete_old_tasks(
        self,
        older_than_timestamp: int,
        status: Optional[ProcessingStatus] = None,
        db: Optional[AsyncSession] = None
    ) -> int:
        """Delete old completed/cancelled tasks for cleanup."""
        async with get_async_db_context(db) as db:
            try:
                stmt = delete(ProcessingTask).where(
                    ProcessingTask.created_at < older_than_timestamp
                )

                if status:
                    stmt = stmt.where(ProcessingTask.status == status.value)
                else:
                    # Only delete terminal states by default
                    stmt = stmt.where(ProcessingTask.status.in_([
                        ProcessingStatus.COMPLETED.value,
                        ProcessingStatus.FAILED.value,
                        ProcessingStatus.CANCELLED.value
                    ]))

                result = await db.execute(stmt)
                await db.commit()
                return result.rowcount or 0
            except Exception as e:
                log.exception(f"Error deleting old tasks: {e}")
                return 0

    async def get_metrics(
        self,
        since_timestamp: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> ProcessingMetrics:
        """Get aggregate processing metrics."""
        async with get_async_db_context(db) as db:
            try:
                from sqlalchemy import func

                # Default to last 24 hours if not specified
                if since_timestamp is None:
                    since_timestamp = int(time.time()) - 86400

                # Queued tasks (current count, not time-filtered)
                queued_result = await db.execute(
                    select(func.count())
                    .select_from(ProcessingTask)
                    .where(ProcessingTask.status == ProcessingStatus.QUEUED.value)
                )
                queued = queued_result.scalar() or 0

                # Processing tasks (current count)
                processing_result = await db.execute(
                    select(func.count())
                    .select_from(ProcessingTask)
                    .where(ProcessingTask.status == ProcessingStatus.PROCESSING.value)
                )
                processing = processing_result.scalar() or 0

                # Completed in time range
                completed_result = await db.execute(
                    select(func.count())
                    .select_from(ProcessingTask)
                    .where(
                        ProcessingTask.status == ProcessingStatus.COMPLETED.value,
                        ProcessingTask.completed_at >= since_timestamp,
                    )
                )
                completed = completed_result.scalar() or 0

                # Failed in time range
                failed_result = await db.execute(
                    select(func.count())
                    .select_from(ProcessingTask)
                    .where(
                        ProcessingTask.status == ProcessingStatus.FAILED.value,
                        ProcessingTask.completed_at >= since_timestamp,
                    )
                )
                failed = failed_result.scalar() or 0

                # Cancelled in time range
                cancelled_result = await db.execute(
                    select(func.count())
                    .select_from(ProcessingTask)
                    .where(
                        ProcessingTask.status == ProcessingStatus.CANCELLED.value,
                        ProcessingTask.completed_at >= since_timestamp,
                    )
                )
                cancelled = cancelled_result.scalar() or 0

                total_tasks = queued + processing + completed + failed + cancelled

                # Average processing time (for completed tasks)
                avg_result = await db.execute(
                    select(func.avg(ProcessingTask.completed_at - ProcessingTask.started_at))
                    .where(
                        ProcessingTask.status == ProcessingStatus.COMPLETED.value,
                        ProcessingTask.started_at.isnot(None),
                        ProcessingTask.completed_at.isnot(None),
                        ProcessingTask.completed_at >= since_timestamp,
                    )
                )
                avg_value = avg_result.scalar()
                avg_processing_time = float(avg_value) if avg_value else None

                # Success rate
                terminal_count = completed + failed
                success_rate = (completed / terminal_count * 100) if terminal_count > 0 else None

                # Chunks processed
                chunks_result = await db.execute(
                    select(func.sum(ProcessingTask.processed_chunks))
                    .where(
                        ProcessingTask.status == ProcessingStatus.COMPLETED.value,
                        ProcessingTask.completed_at >= since_timestamp,
                    )
                )
                chunks_value = chunks_result.scalar()
                chunks_processed = int(chunks_value) if chunks_value else 0

                return ProcessingMetrics(
                    total_tasks=total_tasks,
                    queued=queued,
                    processing=processing,
                    completed=completed,
                    failed=failed,
                    cancelled=cancelled,
                    avg_processing_time=avg_processing_time,
                    success_rate=success_rate,
                    documents_processed=completed,
                    chunks_processed=chunks_processed,
                )
            except Exception as e:
                log.exception(f"Error getting metrics: {e}")
                return ProcessingMetrics()


# Singleton instance
ProcessingTasks = ProcessingTasksTable()


####################
# Progress Tracker
####################


class ProcessingTaskTracker:
    """
    Helper class to track progress of a processing task throughout the pipeline.

    This can be passed through functions to update progress without needing
    direct database access at each step.
    """

    def __init__(self, task_id: str, db: Optional[AsyncSession] = None):
        self.task_id = task_id
        self._db = db
        self._cancelled = False

    async def update_stage(
        self,
        stage: ProcessingStage,
        progress: Optional[float] = None,
        total_chunks: Optional[int] = None,
        processed_chunks: Optional[int] = None,
        current_batch: Optional[int] = None,
    ) -> Optional[ProcessingTaskModel]:
        """Update the task stage and optionally progress details."""
        if progress is None:
            progress = get_progress_for_stage(stage, 0.0)

        update_data = ProcessingTaskUpdate(
            stage=stage.value,
            progress=progress,
            total_chunks=total_chunks,
            processed_chunks=processed_chunks,
            current_batch=current_batch,
        )

        result = await ProcessingTasks.update_task(self.task_id, update_data, db=self._db)

        # Check for cancellation
        if result and result.cancel_requested:
            self._cancelled = True

        return result

    async def update_embedding_progress(
        self,
        processed_chunks: int,
        total_chunks: int,
        current_batch: int,
    ) -> Optional[ProcessingTaskModel]:
        """Update progress during embedding phase."""
        # Calculate progress within embedding stage (0.0 to 1.0)
        stage_progress = processed_chunks / total_chunks if total_chunks > 0 else 0.0
        overall_progress = get_progress_for_stage(ProcessingStage.EMBEDDING, stage_progress)

        update_data = ProcessingTaskUpdate(
            progress=overall_progress,
            processed_chunks=processed_chunks,
            current_batch=current_batch,
        )

        result = await ProcessingTasks.update_task(self.task_id, update_data, db=self._db)

        # Check for cancellation
        if result and result.cancel_requested:
            self._cancelled = True

        return result

    async def complete(self) -> Optional[ProcessingTaskModel]:
        """Mark the task as completed."""
        return await ProcessingTasks.complete_task(self.task_id, db=self._db)

    async def fail(self, error_message: str, error_details: Optional[dict] = None) -> Optional[ProcessingTaskModel]:
        """Mark the task as failed."""
        return await ProcessingTasks.fail_task(self.task_id, error_message, error_details, db=self._db)

    async def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        if self._cancelled:
            return True

        # Refresh from database
        task = await ProcessingTasks.get_task_by_id(self.task_id, db=self._db)
        if task and task.cancel_requested:
            self._cancelled = True

        return self._cancelled

    async def cancel(self) -> Optional[ProcessingTaskModel]:
        """Mark the task as cancelled."""
        return await ProcessingTasks.cancel_task(self.task_id, db=self._db)


class ProcessingCancelledException(Exception):
    """Exception raised when a processing task is cancelled."""
    pass
