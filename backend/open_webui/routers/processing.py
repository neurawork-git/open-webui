"""
Admin API endpoints for document processing task management.

This module provides REST API endpoints for the document processing dashboard,
allowing admins to monitor, manage, and troubleshoot processing operations.
"""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import desc, asc
from sqlalchemy.orm import Session

from open_webui.internal.db import get_session
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
    ProcessingTaskTracker,
    can_cancel,
    can_retry,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_admin_user, get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()


####################
# List Processing Tasks
####################


@router.get("/tasks", response_model=ProcessingTaskListResponse)
async def list_processing_tasks(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    stage: Optional[str] = Query(None, description="Filter by processing stage"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    search: Optional[str] = Query(None, description="Search document name"),
    limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc or desc)"),
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    List all processing tasks with filtering and pagination.

    Admin only endpoint.
    """
    try:
        query = db.query(ProcessingTask)

        # Apply filters
        if status_filter:
            query = query.filter(ProcessingTask.status == status_filter)
        if stage:
            query = query.filter(ProcessingTask.stage == stage)
        if user_id:
            query = query.filter(ProcessingTask.user_id == user_id)
        if document_type:
            query = query.filter(ProcessingTask.document_type == document_type)
        if search:
            query = query.filter(ProcessingTask.document_name.ilike(f"%{search}%"))

        # Get total count before pagination
        total = query.count()

        # Apply sorting
        sort_column = getattr(ProcessingTask, sort_by, ProcessingTask.created_at)
        if sort_order.lower() == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))

        # Apply pagination
        tasks = query.offset(offset).limit(limit).all()

        # Convert to response models with elapsed time calculation
        items = []
        current_time = int(time.time())
        for task in tasks:
            item = ProcessingTaskResponse(
                id=task.id,
                document_id=task.document_id,
                document_name=task.document_name,
                document_type=task.document_type,
                user_id=task.user_id,
                chat_id=task.chat_id,
                status=task.status,
                stage=task.stage,
                progress=task.progress,
                created_at=task.created_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                elapsed_seconds=(
                    (task.completed_at or current_time) - task.started_at
                    if task.started_at
                    else None
                ),
                total_chunks=task.total_chunks,
                processed_chunks=task.processed_chunks,
                retry_count=task.retry_count,
                error_message=task.error_message,
                cancel_requested=task.cancel_requested,
            )
            items.append(item)

        return ProcessingTaskListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        log.exception(f"Error listing processing tasks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing processing tasks: {str(e)}",
        )


####################
# Get Single Task
####################


@router.get("/tasks/{task_id}", response_model=ProcessingTaskResponse)
async def get_processing_task(
    task_id: str,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Get detailed information about a specific processing task.

    Admin only endpoint.
    """
    task = db.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing task not found",
        )

    current_time = int(time.time())
    return ProcessingTaskResponse(
        id=task.id,
        document_id=task.document_id,
        document_name=task.document_name,
        document_type=task.document_type,
        user_id=task.user_id,
        chat_id=task.chat_id,
        status=task.status,
        stage=task.stage,
        progress=task.progress,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        elapsed_seconds=(
            (task.completed_at or current_time) - task.started_at
            if task.started_at
            else None
        ),
        total_chunks=task.total_chunks,
        processed_chunks=task.processed_chunks,
        retry_count=task.retry_count,
        error_message=task.error_message,
        cancel_requested=task.cancel_requested,
    )


####################
# Cancel Task
####################


class CancelTaskRequest(BaseModel):
    immediate: bool = False
    reason: Optional[str] = None


@router.post("/tasks/{task_id}/cancel")
async def cancel_processing_task(
    task_id: str,
    request: Optional[CancelTaskRequest] = None,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Request cancellation of a processing task.

    This sets the cancel_requested flag in the database. The worker will
    check this flag and stop processing at the next batch boundary.

    Admin only endpoint.
    """
    task = db.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing task not found",
        )

    # Check if task can be cancelled
    try:
        current_stage = ProcessingStage(task.stage)
        if not can_cancel(current_stage):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel task in {task.stage} stage",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task stage: {task.stage}",
        )

    # Set cancellation flag
    task.cancel_requested = True
    task.cancelled_by = user.id
    task.cancelled_at = int(time.time())

    # Store reason in task_metadata if provided
    if request and request.reason:
        task.task_metadata = {**(task.task_metadata or {}), "cancellation_reason": request.reason}

    db.commit()

    log.info(f"Cancellation requested for task {task_id} by user {user.id}")

    return {
        "success": True,
        "message": "Cancellation requested",
        "task_id": task_id,
    }


####################
# Retry Task
####################


@router.post("/tasks/{task_id}/retry")
async def retry_processing_task(
    request: Request,
    task_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Retry a failed processing task.

    This resets the task state to QUEUED and re-triggers the file processing.
    The original task record is preserved (updated, not replaced).

    Admin only endpoint.
    """
    from open_webui.models.files import Files
    from open_webui.routers.retrieval import _process_file_impl, ProcessFileForm

    # Get the task first to check if it can be retried
    task = db.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing task not found",
        )

    if task.stage != ProcessingStage.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry task in {task.stage} stage. Only failed tasks can be retried.",
        )

    # Check if the document still exists
    if not task.document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task has no associated document ID",
        )

    file = Files.get_file_by_id(task.document_id, db=db)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated file not found. It may have been deleted.",
        )

    # Reset the task state
    result = ProcessingTasks.retry_task(task_id, db=db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset task state for retry.",
        )

    log.info(f"Task {task_id} queued for retry by user {user.id}, retry_count={result.retry_count}")

    # Get the file owner for processing
    file_user = Users.get_user_by_id(file.user_id)
    if not file_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File owner not found",
        )

    # Re-trigger file processing in background
    def reprocess_file():
        from open_webui.internal.db import SessionLocal
        with SessionLocal() as new_db:
            try:
                tracker = ProcessingTaskTracker(task_id, db=new_db)
                form_data = ProcessFileForm(
                    file_id=task.document_id,
                    collection_name=file.meta.get("collection_name") if file.meta else None,
                )
                _process_file_impl(request, form_data, file_user, new_db, tracker)
            except Exception as e:
                log.exception(f"Error reprocessing file {task.document_id}: {e}")
                ProcessingTasks.fail_task(task_id, str(e), db=new_db)

    background_tasks.add_task(reprocess_file)

    return {
        "success": True,
        "message": "Task queued for retry and reprocessing started",
        "task_id": task_id,
        "retry_count": result.retry_count,
    }


####################
# Delete Task
####################


@router.delete("/tasks/{task_id}")
async def delete_processing_task(
    task_id: str,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Delete a processing task record.

    Only completed, failed, or cancelled tasks can be deleted.

    Admin only endpoint.
    """
    task = db.get(ProcessingTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing task not found",
        )

    # Only allow deletion of terminal states
    if task.status not in [
        ProcessingStatus.COMPLETED.value,
        ProcessingStatus.FAILED.value,
        ProcessingStatus.CANCELLED.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete active task. Cancel it first.",
        )

    result = ProcessingTasks.delete_task(task_id, db=db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete task",
        )

    log.info(f"Task {task_id} deleted by user {user.id}")

    return {
        "success": True,
        "message": "Task deleted",
        "task_id": task_id,
    }


####################
# Get Metrics
####################


@router.get("/metrics", response_model=ProcessingMetrics)
async def get_processing_metrics(
    time_range: str = Query("24h", description="Time range: 1h, 24h, 7d, 30d"),
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Get aggregate processing metrics.

    Admin only endpoint.
    """
    # Convert time range to timestamp
    current_time = int(time.time())
    range_mapping = {
        "1h": 3600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
    }

    seconds_ago = range_mapping.get(time_range, 86400)
    since_timestamp = current_time - seconds_ago

    return ProcessingTasks.get_metrics(since_timestamp=since_timestamp, db=db)


####################
# Bulk Operations
####################


class BulkCancelRequest(BaseModel):
    task_ids: List[str]
    reason: Optional[str] = None


@router.post("/tasks/bulk/cancel")
async def bulk_cancel_tasks(
    request: BulkCancelRequest,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Cancel multiple processing tasks at once.

    Admin only endpoint.
    """
    cancelled = []
    failed = []
    current_time = int(time.time())

    for task_id in request.task_ids:
        task = db.get(ProcessingTask, task_id)
        if not task:
            failed.append({"task_id": task_id, "reason": "Not found"})
            continue

        try:
            current_stage = ProcessingStage(task.stage)
            if not can_cancel(current_stage):
                failed.append({"task_id": task_id, "reason": f"Cannot cancel in {task.stage} stage"})
                continue
        except ValueError:
            failed.append({"task_id": task_id, "reason": f"Invalid stage: {task.stage}"})
            continue

        task.cancel_requested = True
        task.cancelled_by = user.id
        task.cancelled_at = current_time
        if request.reason:
            task.task_metadata = {**(task.task_metadata or {}), "cancellation_reason": request.reason}

        cancelled.append(task_id)

    db.commit()

    log.info(f"Bulk cancellation: {len(cancelled)} cancelled, {len(failed)} failed, by user {user.id}")

    return {
        "success": True,
        "cancelled": cancelled,
        "failed": failed,
    }


class BulkRetryRequest(BaseModel):
    task_ids: List[str]


@router.post("/tasks/bulk/retry")
async def bulk_retry_tasks(
    request: BulkRetryRequest,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Retry multiple failed tasks at once.

    Admin only endpoint.
    """
    retried = []
    failed = []

    for task_id in request.task_ids:
        result = ProcessingTasks.retry_task(task_id, db=db)
        if result:
            retried.append(task_id)
        else:
            failed.append({"task_id": task_id, "reason": "Not found or not in FAILED state"})

    log.info(f"Bulk retry: {len(retried)} retried, {len(failed)} failed, by user {user.id}")

    return {
        "success": True,
        "retried": retried,
        "failed": failed,
    }


class BulkDeleteRequest(BaseModel):
    task_ids: List[str]


@router.post("/tasks/bulk/delete")
async def bulk_delete_tasks(
    request: BulkDeleteRequest,
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Delete multiple completed/failed/cancelled tasks at once.

    Admin only endpoint.
    """
    deleted = []
    failed = []

    terminal_states = [
        ProcessingStatus.COMPLETED.value,
        ProcessingStatus.FAILED.value,
        ProcessingStatus.CANCELLED.value,
    ]

    for task_id in request.task_ids:
        task = db.get(ProcessingTask, task_id)
        if not task:
            failed.append({"task_id": task_id, "reason": "Not found"})
            continue

        if task.status not in terminal_states:
            failed.append({"task_id": task_id, "reason": "Task is still active"})
            continue

        result = ProcessingTasks.delete_task(task_id, db=db)
        if result:
            deleted.append(task_id)
        else:
            failed.append({"task_id": task_id, "reason": "Delete failed"})

    log.info(f"Bulk delete: {len(deleted)} deleted, {len(failed)} failed, by user {user.id}")

    return {
        "success": True,
        "deleted": deleted,
        "failed": failed,
    }


####################
# Cleanup Old Tasks
####################


@router.post("/cleanup")
async def cleanup_old_tasks(
    days: int = Query(30, ge=1, le=365, description="Delete tasks older than this many days"),
    status_filter: Optional[str] = Query(None, alias="status", description="Only delete tasks with this status"),
    user=Depends(get_admin_user),
    db: Session = Depends(get_session),
):
    """
    Delete old processing tasks to clean up the database.

    By default, only deletes completed/failed/cancelled tasks older than 30 days.

    Admin only endpoint.
    """
    older_than = int(time.time()) - (days * 86400)

    status_enum = None
    if status_filter:
        try:
            status_enum = ProcessingStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    count = ProcessingTasks.delete_old_tasks(
        older_than_timestamp=older_than,
        status=status_enum,
        db=db,
    )

    log.info(f"Cleanup: deleted {count} tasks older than {days} days, by user {user.id}")

    return {
        "success": True,
        "deleted_count": count,
        "older_than_days": days,
    }
