/**
 * Admin API client for document processing dashboard.
 *
 * Provides functions to list, filter, cancel, retry, and manage processing tasks.
 */

import { WEBUI_API_BASE_URL } from '$lib/constants';

const API_BASE = `${WEBUI_API_BASE_URL}/admin/processing`;

// ==================== Types ====================

export type ProcessingStatus =
	| 'queued'
	| 'processing'
	| 'completed'
	| 'failed'
	| 'cancelled';

export type ProcessingStage =
	| 'queued'
	| 'extracting'
	| 'chunking'
	| 'embedding'
	| 'indexing'
	| 'completed'
	| 'failed'
	| 'cancelled';

export type DocumentType = 'file_upload' | 'web_scrape' | 'knowledge_sync' | 'api_upload';

export interface ProcessingTask {
	id: string;
	document_id: string | null;
	document_name: string;
	document_type: DocumentType;
	user_id: string;
	chat_id: string | null;
	status: ProcessingStatus;
	stage: ProcessingStage;
	progress: number;
	created_at: number;
	started_at: number | null;
	completed_at: number | null;
	elapsed_seconds: number | null;
	total_chunks: number | null;
	processed_chunks: number | null;
	retry_count: number;
	error_message: string | null;
	cancel_requested: boolean;
}

export interface ProcessingTaskListResponse {
	items: ProcessingTask[];
	total: number;
	limit: number;
	offset: number;
}

export interface ProcessingMetrics {
	total_tasks: number;
	queued: number;
	processing: number;
	completed: number;
	failed: number;
	cancelled: number;
	avg_processing_time: number | null;
	success_rate: number | null;
	documents_processed: number;
	chunks_processed: number;
}

export interface TaskListParams {
	status?: ProcessingStatus;
	stage?: ProcessingStage;
	userId?: string;
	documentType?: DocumentType;
	search?: string;
	limit?: number;
	offset?: number;
	sortBy?: string;
	sortOrder?: 'asc' | 'desc';
}

export interface BulkOperationResult {
	success: boolean;
	cancelled?: string[];
	retried?: string[];
	deleted?: string[];
	failed?: { task_id: string; reason: string }[];
}

// ==================== API Functions ====================

/**
 * List processing tasks with filtering and pagination.
 */
export const getProcessingTasks = async (
	token: string,
	params: TaskListParams = {}
): Promise<ProcessingTaskListResponse> => {
	const queryParams = new URLSearchParams();

	if (params.status) queryParams.append('status', params.status);
	if (params.stage) queryParams.append('stage', params.stage);
	if (params.userId) queryParams.append('user_id', params.userId);
	if (params.documentType) queryParams.append('document_type', params.documentType);
	if (params.search) queryParams.append('search', params.search);
	if (params.limit !== undefined) queryParams.append('limit', String(params.limit));
	if (params.offset !== undefined) queryParams.append('offset', String(params.offset));
	if (params.sortBy) queryParams.append('sort_by', params.sortBy);
	if (params.sortOrder) queryParams.append('sort_order', params.sortOrder);

	const res = await fetch(`${API_BASE}/tasks?${queryParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to fetch processing tasks');
	}

	return res.json();
};

/**
 * Get a single processing task by ID.
 */
export const getProcessingTask = async (
	token: string,
	taskId: string
): Promise<ProcessingTask> => {
	const res = await fetch(`${API_BASE}/tasks/${taskId}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to fetch processing task');
	}

	return res.json();
};

/**
 * Request cancellation of a processing task.
 */
export const cancelProcessingTask = async (
	token: string,
	taskId: string,
	reason?: string
): Promise<{ success: boolean; message: string; task_id: string }> => {
	const res = await fetch(`${API_BASE}/tasks/${taskId}/cancel`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ reason })
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to cancel processing task');
	}

	return res.json();
};

/**
 * Retry a failed processing task.
 */
export const retryProcessingTask = async (
	token: string,
	taskId: string
): Promise<{ success: boolean; message: string; task_id: string; retry_count: number }> => {
	const res = await fetch(`${API_BASE}/tasks/${taskId}/retry`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to retry processing task');
	}

	return res.json();
};

/**
 * Delete a processing task record.
 */
export const deleteProcessingTask = async (
	token: string,
	taskId: string
): Promise<{ success: boolean; message: string; task_id: string }> => {
	const res = await fetch(`${API_BASE}/tasks/${taskId}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to delete processing task');
	}

	return res.json();
};

/**
 * Get aggregate processing metrics.
 */
export const getProcessingMetrics = async (
	token: string,
	timeRange: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<ProcessingMetrics> => {
	const res = await fetch(`${API_BASE}/metrics?time_range=${timeRange}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to fetch processing metrics');
	}

	return res.json();
};

/**
 * Cancel multiple processing tasks at once.
 */
export const bulkCancelTasks = async (
	token: string,
	taskIds: string[],
	reason?: string
): Promise<BulkOperationResult> => {
	const res = await fetch(`${API_BASE}/tasks/bulk/cancel`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ task_ids: taskIds, reason })
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to bulk cancel tasks');
	}

	return res.json();
};

/**
 * Retry multiple failed tasks at once.
 */
export const bulkRetryTasks = async (
	token: string,
	taskIds: string[]
): Promise<BulkOperationResult> => {
	const res = await fetch(`${API_BASE}/tasks/bulk/retry`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ task_ids: taskIds })
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to bulk retry tasks');
	}

	return res.json();
};

/**
 * Delete multiple completed/failed/cancelled tasks at once.
 */
export const bulkDeleteTasks = async (
	token: string,
	taskIds: string[]
): Promise<BulkOperationResult> => {
	const res = await fetch(`${API_BASE}/tasks/bulk/delete`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ task_ids: taskIds })
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to bulk delete tasks');
	}

	return res.json();
};

/**
 * Clean up old processing tasks.
 */
export const cleanupOldTasks = async (
	token: string,
	days: number = 30,
	status?: ProcessingStatus
): Promise<{ success: boolean; deleted_count: number; older_than_days: number }> => {
	const queryParams = new URLSearchParams();
	queryParams.append('days', String(days));
	if (status) queryParams.append('status', status);

	const res = await fetch(`${API_BASE}/cleanup?${queryParams.toString()}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const error = await res.json();
		throw new Error(error.detail || 'Failed to cleanup old tasks');
	}

	return res.json();
};
