/**
 * Svelte stores for document processing dashboard.
 *
 * Provides reactive stores with polling for real-time updates
 * of processing tasks and metrics.
 */

import { writable, derived, get } from 'svelte/store';
import type { Writable, Readable } from 'svelte/store';
import {
	getProcessingTasks,
	getProcessingMetrics,
	type ProcessingTask,
	type ProcessingTaskListResponse,
	type ProcessingMetrics,
	type ProcessingStatus,
	type ProcessingStage,
	type DocumentType,
	type TaskListParams
} from '$lib/apis/admin/processing';

// ==================== Types ====================

export interface ProcessingFilters {
	status: ProcessingStatus | null;
	stage: ProcessingStage | null;
	documentType: DocumentType | null;
	userId: string | null;
	search: string;
}

export interface ProcessingPagination {
	limit: number;
	offset: number;
	total: number;
}

export interface ProcessingSorting {
	sortBy: string;
	sortOrder: 'asc' | 'desc';
}

export interface ProcessingStoreState {
	tasks: ProcessingTask[];
	metrics: ProcessingMetrics | null;
	filters: ProcessingFilters;
	pagination: ProcessingPagination;
	sorting: ProcessingSorting;
	selectedTaskIds: Set<string>;
	isLoading: boolean;
	isPolling: boolean;
	error: string | null;
	lastUpdated: number | null;
}

// ==================== Default Values ====================

const defaultFilters: ProcessingFilters = {
	status: null,
	stage: null,
	documentType: null,
	userId: null,
	search: ''
};

const defaultPagination: ProcessingPagination = {
	limit: 50,
	offset: 0,
	total: 0
};

const defaultSorting: ProcessingSorting = {
	sortBy: 'created_at',
	sortOrder: 'desc'
};

const defaultState: ProcessingStoreState = {
	tasks: [],
	metrics: null,
	filters: { ...defaultFilters },
	pagination: { ...defaultPagination },
	sorting: { ...defaultSorting },
	selectedTaskIds: new Set(),
	isLoading: false,
	isPolling: false,
	error: null,
	lastUpdated: null
};

// ==================== Store Implementation ====================

function createProcessingStore() {
	const { subscribe, set, update } = writable<ProcessingStoreState>({ ...defaultState });

	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let token: string = '';
	let metricsTimeRange: '1h' | '24h' | '7d' | '30d' = '24h';

	/**
	 * Set authentication token for API calls.
	 */
	function setToken(newToken: string) {
		token = newToken;
	}

	/**
	 * Build API params from current store state.
	 */
	function buildParams(state: ProcessingStoreState): TaskListParams {
		const params: TaskListParams = {
			limit: state.pagination.limit,
			offset: state.pagination.offset,
			sortBy: state.sorting.sortBy,
			sortOrder: state.sorting.sortOrder
		};

		if (state.filters.status) params.status = state.filters.status;
		if (state.filters.stage) params.stage = state.filters.stage;
		if (state.filters.documentType) params.documentType = state.filters.documentType;
		if (state.filters.userId) params.userId = state.filters.userId;
		if (state.filters.search) params.search = state.filters.search;

		return params;
	}

	/**
	 * Fetch tasks from API and update store.
	 */
	async function fetchTasks(showLoading = true) {
		if (!token) {
			console.warn('ProcessingStore: No token set, skipping fetch');
			return;
		}

		const currentState = get({ subscribe });

		if (showLoading) {
			update((s) => ({ ...s, isLoading: true, error: null }));
		}

		try {
			const params = buildParams(currentState);
			const response: ProcessingTaskListResponse = await getProcessingTasks(token, params);

			update((s) => ({
				...s,
				tasks: response.items,
				pagination: {
					...s.pagination,
					total: response.total
				},
				isLoading: false,
				error: null,
				lastUpdated: Date.now()
			}));
		} catch (err) {
			const errorMessage = err instanceof Error ? err.message : 'Failed to fetch tasks';
			update((s) => ({
				...s,
				isLoading: false,
				error: errorMessage
			}));
			console.error('ProcessingStore: Failed to fetch tasks:', err);
		}
	}

	/**
	 * Fetch metrics from API and update store.
	 */
	async function fetchMetrics() {
		if (!token) return;

		try {
			const metrics = await getProcessingMetrics(token, metricsTimeRange);
			update((s) => ({ ...s, metrics }));
		} catch (err) {
			console.error('ProcessingStore: Failed to fetch metrics:', err);
		}
	}

	/**
	 * Start polling for updates.
	 */
	function startPolling(intervalMs = 5000) {
		if (pollInterval) {
			clearInterval(pollInterval);
		}

		update((s) => ({ ...s, isPolling: true }));

		// Initial fetch
		fetchTasks(false);
		fetchMetrics();

		// Set up interval
		pollInterval = setInterval(() => {
			fetchTasks(false);
			fetchMetrics();
		}, intervalMs);
	}

	/**
	 * Stop polling for updates.
	 */
	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
		update((s) => ({ ...s, isPolling: false }));
	}

	/**
	 * Refresh data immediately.
	 */
	async function refresh() {
		await Promise.all([fetchTasks(true), fetchMetrics()]);
	}

	/**
	 * Update filters and reset pagination.
	 */
	function setFilters(filters: Partial<ProcessingFilters>) {
		update((s) => ({
			...s,
			filters: { ...s.filters, ...filters },
			pagination: { ...s.pagination, offset: 0 }
		}));

		// Fetch with new filters
		fetchTasks();
	}

	/**
	 * Reset all filters to defaults.
	 */
	function resetFilters() {
		update((s) => ({
			...s,
			filters: { ...defaultFilters },
			pagination: { ...defaultPagination }
		}));

		fetchTasks();
	}

	/**
	 * Update pagination.
	 */
	function setPagination(pagination: Partial<ProcessingPagination>) {
		update((s) => ({
			...s,
			pagination: { ...s.pagination, ...pagination }
		}));

		fetchTasks();
	}

	/**
	 * Go to specific page.
	 */
	function goToPage(page: number) {
		const currentState = get({ subscribe });
		const newOffset = (page - 1) * currentState.pagination.limit;
		setPagination({ offset: newOffset });
	}

	/**
	 * Update sorting.
	 */
	function setSorting(sorting: Partial<ProcessingSorting>) {
		update((s) => ({
			...s,
			sorting: { ...s.sorting, ...sorting }
		}));

		fetchTasks();
	}

	/**
	 * Set metrics time range and refresh.
	 */
	function setMetricsTimeRange(range: '1h' | '24h' | '7d' | '30d') {
		metricsTimeRange = range;
		fetchMetrics();
	}

	/**
	 * Toggle task selection.
	 */
	function toggleTaskSelection(taskId: string) {
		update((s) => {
			const newSet = new Set(s.selectedTaskIds);
			if (newSet.has(taskId)) {
				newSet.delete(taskId);
			} else {
				newSet.add(taskId);
			}
			return { ...s, selectedTaskIds: newSet };
		});
	}

	/**
	 * Select all visible tasks.
	 */
	function selectAllTasks() {
		update((s) => ({
			...s,
			selectedTaskIds: new Set(s.tasks.map((t) => t.id))
		}));
	}

	/**
	 * Clear all selections.
	 */
	function clearSelection() {
		update((s) => ({ ...s, selectedTaskIds: new Set() }));
	}

	/**
	 * Remove a task from the local store (after delete).
	 */
	function removeTask(taskId: string) {
		update((s) => ({
			...s,
			tasks: s.tasks.filter((t) => t.id !== taskId),
			selectedTaskIds: new Set([...s.selectedTaskIds].filter((id) => id !== taskId)),
			pagination: {
				...s.pagination,
				total: Math.max(0, s.pagination.total - 1)
			}
		}));
	}

	/**
	 * Update a specific task in the local store.
	 */
	function updateTask(taskId: string, updates: Partial<ProcessingTask>) {
		update((s) => ({
			...s,
			tasks: s.tasks.map((t) => (t.id === taskId ? { ...t, ...updates } : t))
		}));
	}

	/**
	 * Reset store to initial state.
	 */
	function reset() {
		stopPolling();
		set({ ...defaultState });
	}

	return {
		subscribe,
		setToken,
		fetchTasks,
		fetchMetrics,
		startPolling,
		stopPolling,
		refresh,
		setFilters,
		resetFilters,
		setPagination,
		goToPage,
		setSorting,
		setMetricsTimeRange,
		toggleTaskSelection,
		selectAllTasks,
		clearSelection,
		removeTask,
		updateTask,
		reset
	};
}

// ==================== Exported Store ====================

export const processingStore = createProcessingStore();

// ==================== Derived Stores ====================

/**
 * Currently active (non-terminal) tasks.
 */
export const activeTasks: Readable<ProcessingTask[]> = derived(
	processingStore,
	($store) => $store.tasks.filter((t) => t.status === 'queued' || t.status === 'processing')
);

/**
 * Failed tasks that can be retried.
 */
export const failedTasks: Readable<ProcessingTask[]> = derived(
	processingStore,
	($store) => $store.tasks.filter((t) => t.status === 'failed')
);

/**
 * Selected tasks as array.
 */
export const selectedTasks: Readable<ProcessingTask[]> = derived(
	processingStore,
	($store) => $store.tasks.filter((t) => $store.selectedTaskIds.has(t.id))
);

/**
 * Current page number (1-indexed).
 */
export const currentPage: Readable<number> = derived(
	processingStore,
	($store) => Math.floor($store.pagination.offset / $store.pagination.limit) + 1
);

/**
 * Total number of pages.
 */
export const totalPages: Readable<number> = derived(
	processingStore,
	($store) => Math.ceil($store.pagination.total / $store.pagination.limit) || 1
);

/**
 * Whether there are any active filters.
 */
export const hasActiveFilters: Readable<boolean> = derived(
	processingStore,
	($store) =>
		$store.filters.status !== null ||
		$store.filters.stage !== null ||
		$store.filters.documentType !== null ||
		$store.filters.userId !== null ||
		$store.filters.search !== ''
);

/**
 * Count of selected tasks.
 */
export const selectedCount: Readable<number> = derived(
	processingStore,
	($store) => $store.selectedTaskIds.size
);

/**
 * Whether all visible tasks are selected.
 */
export const allSelected: Readable<boolean> = derived(
	processingStore,
	($store) =>
		$store.tasks.length > 0 && $store.tasks.every((t) => $store.selectedTaskIds.has(t.id))
);
