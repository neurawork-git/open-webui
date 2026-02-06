<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { user } from '$lib/stores';
	import {
		processingStore,
		activeTasks,
		failedTasks,
		currentPage,
		totalPages,
		hasActiveFilters,
		selectedCount,
		allSelected,
		selectedTasks
	} from '$lib/stores/processing';
	import {
		cancelProcessingTask,
		retryProcessingTask,
		deleteProcessingTask,
		bulkCancelTasks,
		bulkRetryTasks,
		bulkDeleteTasks,
		type ProcessingTask,
		type ProcessingStatus,
		type ProcessingStage
	} from '$lib/apis/admin/processing';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let token = '';

	// Poll interval in milliseconds
	const POLL_INTERVAL = 3000;

	// Error details modal state
	let showErrorModal = false;
	let selectedErrorTask: ProcessingTask | null = null;

	// Bulk operations loading state
	let bulkOperationLoading = false;

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
			return;
		}

		token = localStorage.getItem('token') || '';
		processingStore.setToken(token);
		processingStore.startPolling(POLL_INTERVAL);
		loaded = true;
	});

	onDestroy(() => {
		processingStore.stopPolling();
	});

	// Helper functions
	function getStatusColor(status: ProcessingStatus): string {
		switch (status) {
			case 'queued':
				return 'bg-gray-400';
			case 'processing':
				return 'bg-blue-500';
			case 'completed':
				return 'bg-green-500';
			case 'failed':
				return 'bg-red-500';
			case 'cancelled':
				return 'bg-yellow-500';
			default:
				return 'bg-gray-400';
		}
	}

	function getStageLabel(stage: ProcessingStage): string {
		const labels: Record<ProcessingStage, string> = {
			queued: 'Queued',
			extracting: 'Extracting',
			chunking: 'Chunking',
			embedding: 'Embedding',
			indexing: 'Indexing',
			completed: 'Completed',
			failed: 'Failed',
			cancelled: 'Cancelled'
		};
		return labels[stage] || stage;
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null || seconds === undefined) return '-';
		if (seconds < 60) return `${seconds}s`;
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}m ${secs}s`;
	}

	function formatTime(timestamp: number | null): string {
		if (!timestamp) return '-';
		return new Date(timestamp * 1000).toLocaleString();
	}

	// Single task actions
	async function handleCancel(task: ProcessingTask) {
		if (!confirm($i18n.t('Are you sure you want to cancel this task?'))) return;

		try {
			await cancelProcessingTask(token, task.id);
			toast.success($i18n.t('Cancellation requested'));
			processingStore.refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Failed to cancel task'));
		}
	}

	async function handleRetry(task: ProcessingTask) {
		try {
			await retryProcessingTask(token, task.id);
			toast.success($i18n.t('Task queued for retry'));
			processingStore.refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Failed to retry task'));
		}
	}

	async function handleDelete(task: ProcessingTask) {
		if (!confirm($i18n.t('Are you sure you want to delete this task record?'))) return;

		try {
			await deleteProcessingTask(token, task.id);
			toast.success($i18n.t('Task deleted'));
			processingStore.removeTask(task.id);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Failed to delete task'));
		}
	}

	function canCancel(task: ProcessingTask): boolean {
		return (
			['queued', 'extracting', 'chunking', 'embedding', 'indexing'].includes(task.stage) &&
			!task.cancel_requested
		);
	}

	function canRetry(task: ProcessingTask): boolean {
		return task.status === 'failed';
	}

	function canDelete(task: ProcessingTask): boolean {
		return ['completed', 'failed', 'cancelled'].includes(task.status);
	}

	// Error modal functions
	function openErrorModal(task: ProcessingTask) {
		selectedErrorTask = task;
		showErrorModal = true;
	}

	function closeErrorModal() {
		showErrorModal = false;
		selectedErrorTask = null;
	}

	// Bulk operations
	async function handleBulkCancel() {
		const taskIds = [...$processingStore.selectedTaskIds];
		const cancellableTasks = $selectedTasks.filter(canCancel);

		if (cancellableTasks.length === 0) {
			toast.error($i18n.t('No selected tasks can be cancelled'));
			return;
		}

		if (!confirm($i18n.t('Are you sure you want to cancel {{count}} task(s)?', { count: cancellableTasks.length }))) {
			return;
		}

		bulkOperationLoading = true;
		try {
			const result = await bulkCancelTasks(token, cancellableTasks.map(t => t.id));
			const successCount = result.cancelled?.length || 0;
			const failCount = result.failed?.length || 0;

			if (successCount > 0) {
				toast.success($i18n.t('Cancelled {{count}} task(s)', { count: successCount }));
			}
			if (failCount > 0) {
				toast.error($i18n.t('Failed to cancel {{count}} task(s)', { count: failCount }));
			}

			processingStore.clearSelection();
			processingStore.refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Bulk cancel failed'));
		} finally {
			bulkOperationLoading = false;
		}
	}

	async function handleBulkRetry() {
		const retryableTasks = $selectedTasks.filter(canRetry);

		if (retryableTasks.length === 0) {
			toast.error($i18n.t('No selected tasks can be retried'));
			return;
		}

		bulkOperationLoading = true;
		try {
			const result = await bulkRetryTasks(token, retryableTasks.map(t => t.id));
			const successCount = result.retried?.length || 0;
			const failCount = result.failed?.length || 0;

			if (successCount > 0) {
				toast.success($i18n.t('Retried {{count}} task(s)', { count: successCount }));
			}
			if (failCount > 0) {
				toast.error($i18n.t('Failed to retry {{count}} task(s)', { count: failCount }));
			}

			processingStore.clearSelection();
			processingStore.refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Bulk retry failed'));
		} finally {
			bulkOperationLoading = false;
		}
	}

	async function handleBulkDelete() {
		const deletableTasks = $selectedTasks.filter(canDelete);

		if (deletableTasks.length === 0) {
			toast.error($i18n.t('No selected tasks can be deleted'));
			return;
		}

		if (!confirm($i18n.t('Are you sure you want to delete {{count}} task record(s)?', { count: deletableTasks.length }))) {
			return;
		}

		bulkOperationLoading = true;
		try {
			const result = await bulkDeleteTasks(token, deletableTasks.map(t => t.id));
			const successCount = result.deleted?.length || 0;
			const failCount = result.failed?.length || 0;

			if (successCount > 0) {
				toast.success($i18n.t('Deleted {{count}} task(s)', { count: successCount }));
			}
			if (failCount > 0) {
				toast.error($i18n.t('Failed to delete {{count}} task(s)', { count: failCount }));
			}

			processingStore.clearSelection();
			processingStore.refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : $i18n.t('Bulk delete failed'));
		} finally {
			bulkOperationLoading = false;
		}
	}

	// Selection helpers
	function handleSelectAll() {
		if ($allSelected) {
			processingStore.clearSelection();
		} else {
			processingStore.selectAllTasks();
		}
	}

	// Filter handling
	let searchInput = '';
	let statusFilter: ProcessingStatus | '' = '';

	function applySearch() {
		processingStore.setFilters({ search: searchInput });
	}

	function applyStatusFilter() {
		processingStore.setFilters({ status: statusFilter || null });
	}

	function clearFilters() {
		searchInput = '';
		statusFilter = '';
		processingStore.resetFilters();
	}
</script>

{#if !loaded}
	<div class="flex justify-center items-center h-64">
		<Spinner />
	</div>
{:else}
	<div class="flex flex-col w-full h-full px-4 pb-4">
		<!-- Header -->
		<div class="flex items-center justify-between mb-4">
			<div>
				<h1 class="text-2xl font-semibold dark:text-white">{$i18n.t('Document Processing')}</h1>
				<p class="text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t('Monitor and manage document processing tasks')}
				</p>
			</div>
			<div class="flex items-center gap-2">
				{#if $processingStore.isPolling}
					<span class="flex items-center text-sm text-green-500">
						<span class="w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"></span>
						{$i18n.t('Live')}
					</span>
				{/if}
				<button
					class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => processingStore.refresh()}
					title={$i18n.t('Refresh')}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-5 h-5 {$processingStore.isLoading ? 'animate-spin' : ''}"
					>
						<path
							fill-rule="evenodd"
							d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Metrics Summary -->
		{#if $processingStore.metrics}
			<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-4">
				<div class="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
					<div class="text-2xl font-bold text-gray-700 dark:text-gray-200">
						{$processingStore.metrics.total_tasks}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Total Tasks')}</div>
				</div>
				<div class="p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20">
					<div class="text-2xl font-bold text-blue-600 dark:text-blue-400">
						{$processingStore.metrics.queued + $processingStore.metrics.processing}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Active')}</div>
				</div>
				<div class="p-4 rounded-lg bg-green-50 dark:bg-green-900/20">
					<div class="text-2xl font-bold text-green-600 dark:text-green-400">
						{$processingStore.metrics.completed}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Completed')}</div>
				</div>
				<div class="p-4 rounded-lg bg-red-50 dark:bg-red-900/20">
					<div class="text-2xl font-bold text-red-600 dark:text-red-400">
						{$processingStore.metrics.failed}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Failed')}</div>
				</div>
				<div class="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
					<div class="text-2xl font-bold text-gray-700 dark:text-gray-200">
						{$processingStore.metrics.avg_processing_time
							? formatDuration(Math.round($processingStore.metrics.avg_processing_time))
							: '-'}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Avg. Time')}</div>
				</div>
				<div class="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
					<div class="text-2xl font-bold text-gray-700 dark:text-gray-200">
						{$processingStore.metrics.success_rate
							? `${Math.round($processingStore.metrics.success_rate)}%`
							: '-'}
					</div>
					<div class="text-sm text-gray-500">{$i18n.t('Success Rate')}</div>
				</div>
			</div>
		{/if}

		<!-- Filters and Bulk Actions -->
		<div class="flex flex-wrap items-center justify-between gap-2 mb-4">
			<div class="flex flex-wrap items-center gap-2">
				<input
					type="text"
					bind:value={searchInput}
					on:keydown={(e) => e.key === 'Enter' && applySearch()}
					placeholder={$i18n.t('Search documents...')}
					class="px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
				<select
					bind:value={statusFilter}
					on:change={applyStatusFilter}
					class="px-3 py-2 pr-8 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer"
				>
					<option value="">{$i18n.t('All Statuses')}</option>
					<option value="queued">{$i18n.t('Queued')}</option>
					<option value="processing">{$i18n.t('Processing')}</option>
					<option value="completed">{$i18n.t('Completed')}</option>
					<option value="failed">{$i18n.t('Failed')}</option>
					<option value="cancelled">{$i18n.t('Cancelled')}</option>
				</select>
				{#if $hasActiveFilters}
					<button
						class="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
						on:click={clearFilters}
					>
						{$i18n.t('Clear Filters')}
					</button>
				{/if}
			</div>

			<!-- Bulk Actions -->
			{#if $selectedCount > 0}
				<div class="flex items-center gap-2">
					<span class="text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t('{{count}} selected', { count: $selectedCount })}
					</span>
					<div class="flex gap-1">
						<Tooltip content={$i18n.t('Cancel Selected')}>
							<button
								class="px-3 py-1.5 text-sm rounded-lg bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 transition disabled:opacity-50"
								on:click={handleBulkCancel}
								disabled={bulkOperationLoading}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 inline-block mr-1"
								>
									<path
										d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
									/>
								</svg>
								{$i18n.t('Cancel')}
							</button>
						</Tooltip>
						<Tooltip content={$i18n.t('Retry Selected')}>
							<button
								class="px-3 py-1.5 text-sm rounded-lg bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50 transition disabled:opacity-50"
								on:click={handleBulkRetry}
								disabled={bulkOperationLoading}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 inline-block mr-1"
								>
									<path
										fill-rule="evenodd"
										d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
										clip-rule="evenodd"
									/>
								</svg>
								{$i18n.t('Retry')}
							</button>
						</Tooltip>
						<Tooltip content={$i18n.t('Delete Selected')}>
							<button
								class="px-3 py-1.5 text-sm rounded-lg bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition disabled:opacity-50"
								on:click={handleBulkDelete}
								disabled={bulkOperationLoading}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 inline-block mr-1"
								>
									<path
										fill-rule="evenodd"
										d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
										clip-rule="evenodd"
									/>
								</svg>
								{$i18n.t('Delete')}
							</button>
						</Tooltip>
					</div>
					<button
						class="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
						on:click={() => processingStore.clearSelection()}
					>
						{$i18n.t('Clear selection')}
					</button>
				</div>
			{/if}
		</div>

		<!-- Error Display -->
		{#if $processingStore.error}
			<div
				class="p-4 mb-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400"
			>
				{$processingStore.error}
			</div>
		{/if}

		<!-- Task Table -->
		<div class="flex-1 overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
			<table class="w-full text-sm">
				<thead class="sticky top-0 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
					<tr>
						<th class="px-4 py-3 text-left w-10">
							<input
								type="checkbox"
								checked={$allSelected && $processingStore.tasks.length > 0}
								on:change={handleSelectAll}
								class="rounded border-gray-300 dark:border-gray-600 text-blue-500 focus:ring-blue-500"
							/>
						</th>
						<th class="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Document')}
						</th>
						<th class="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Status')}
						</th>
						<th class="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Progress')}
						</th>
						<th class="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Started')}
						</th>
						<th class="px-4 py-3 text-left font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Duration')}
						</th>
						<th class="px-4 py-3 text-right font-medium text-gray-500 dark:text-gray-400">
							{$i18n.t('Actions')}
						</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-200 dark:divide-gray-700">
					{#if $processingStore.tasks.length === 0}
						<tr>
							<td colspan="7" class="px-4 py-8 text-center text-gray-500">
								{$processingStore.isLoading
									? $i18n.t('Loading...')
									: $i18n.t('No processing tasks found')}
							</td>
						</tr>
					{:else}
						{#each $processingStore.tasks as task (task.id)}
							<tr class="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition {$processingStore.selectedTaskIds.has(task.id) ? 'bg-blue-50 dark:bg-blue-900/20' : ''}">
								<td class="px-4 py-3">
									<input
										type="checkbox"
										checked={$processingStore.selectedTaskIds.has(task.id)}
										on:change={() => processingStore.toggleTaskSelection(task.id)}
										class="rounded border-gray-300 dark:border-gray-600 text-blue-500 focus:ring-blue-500"
									/>
								</td>
								<td class="px-4 py-3">
									<div class="font-medium text-gray-900 dark:text-white truncate max-w-xs">
										{task.document_name}
									</div>
									<div class="text-xs text-gray-500">
										{task.document_type}
									</div>
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<span
											class="w-2 h-2 rounded-full {getStatusColor(task.status)}"
										></span>
										<span class="capitalize">{getStageLabel(task.stage)}</span>
										{#if task.cancel_requested && task.status !== 'cancelled'}
											<span class="text-xs text-yellow-500">(Cancelling...)</span>
										{/if}
									</div>
								</td>
								<td class="px-4 py-3">
									<div class="w-full max-w-[150px]">
										<div
											class="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden"
										>
											<div
												class="h-full {getStatusColor(task.status)} transition-all duration-300"
												style="width: {task.progress * 100}%"
											></div>
										</div>
										<div class="text-xs text-gray-500 mt-1">
											{Math.round(task.progress * 100)}%
											{#if task.total_chunks}
												({task.processed_chunks}/{task.total_chunks} chunks)
											{/if}
										</div>
									</div>
								</td>
								<td class="px-4 py-3 text-gray-500">
									{formatTime(task.started_at)}
								</td>
								<td class="px-4 py-3 text-gray-500">
									{formatDuration(task.elapsed_seconds)}
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center justify-end gap-1">
										{#if canCancel(task)}
											<Tooltip content={$i18n.t('Cancel')}>
												<button
													class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 hover:text-red-500 transition"
													on:click={() => handleCancel(task)}
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="w-4 h-4"
													>
														<path
															d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
										{#if canRetry(task)}
											<Tooltip content={$i18n.t('Retry')}>
												<button
													class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 hover:text-blue-500 transition"
													on:click={() => handleRetry(task)}
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="w-4 h-4"
													>
														<path
															fill-rule="evenodd"
															d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
															clip-rule="evenodd"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
										{#if canDelete(task)}
											<Tooltip content={$i18n.t('Delete')}>
												<button
													class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 hover:text-red-500 transition"
													on:click={() => handleDelete(task)}
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="w-4 h-4"
													>
														<path
															fill-rule="evenodd"
															d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
															clip-rule="evenodd"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
										{#if task.error_message}
											<Tooltip content={$i18n.t('View Error Details')}>
												<button
													class="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-red-500 transition"
													on:click={() => openErrorModal(task)}
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="w-4 h-4"
													>
														<path
															fill-rule="evenodd"
															d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z"
															clip-rule="evenodd"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
									</div>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>

		<!-- Pagination -->
		{#if $processingStore.pagination.total > $processingStore.pagination.limit}
			<div class="mt-4 flex justify-between items-center">
				<div class="text-sm text-gray-500">
					{$i18n.t('Showing')}
					{$processingStore.pagination.offset + 1} -
					{Math.min(
						$processingStore.pagination.offset + $processingStore.pagination.limit,
						$processingStore.pagination.total
					)}
					{$i18n.t('of')}
					{$processingStore.pagination.total}
				</div>
				<div class="flex gap-2">
					<button
						class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-50"
						disabled={$currentPage === 1}
						on:click={() => processingStore.goToPage($currentPage - 1)}
					>
						{$i18n.t('Previous')}
					</button>
					<span class="px-3 py-1.5 text-sm">
						{$currentPage} / {$totalPages}
					</span>
					<button
						class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 disabled:opacity-50"
						disabled={$currentPage === $totalPages}
						on:click={() => processingStore.goToPage($currentPage + 1)}
					>
						{$i18n.t('Next')}
					</button>
				</div>
			</div>
		{/if}

		<!-- Last Updated -->
		{#if $processingStore.lastUpdated}
			<div class="mt-2 text-xs text-gray-400 text-right">
				{$i18n.t('Last updated')}: {new Date($processingStore.lastUpdated).toLocaleTimeString()}
			</div>
		{/if}
	</div>

	<!-- Error Details Modal -->
	{#if showErrorModal && selectedErrorTask}
		<Modal size="md" show={showErrorModal} on:close={closeErrorModal}>
			<div class="p-6">
				<div class="flex items-start justify-between mb-4">
					<div class="flex items-center gap-3">
						<div class="p-2 rounded-full bg-red-100 dark:bg-red-900/30">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="w-6 h-6 text-red-600 dark:text-red-400"
							>
								<path
									fill-rule="evenodd"
									d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
						<div>
							<h3 class="text-lg font-semibold dark:text-white">{$i18n.t('Error Details')}</h3>
							<p class="text-sm text-gray-500">{$i18n.t('Processing task failed')}</p>
						</div>
					</div>
					<button
						class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition"
						on:click={closeErrorModal}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-5 h-5 text-gray-500"
						>
							<path
								d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
							/>
						</svg>
					</button>
				</div>

				<!-- Task Info -->
				<div class="mb-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
					<div class="grid grid-cols-2 gap-4 text-sm">
						<div>
							<span class="text-gray-500">{$i18n.t('Document')}:</span>
							<span class="ml-2 font-medium dark:text-white">{selectedErrorTask.document_name}</span>
						</div>
						<div>
							<span class="text-gray-500">{$i18n.t('Type')}:</span>
							<span class="ml-2 font-medium dark:text-white">{selectedErrorTask.document_type}</span>
						</div>
						<div>
							<span class="text-gray-500">{$i18n.t('Stage')}:</span>
							<span class="ml-2 font-medium dark:text-white">{getStageLabel(selectedErrorTask.stage)}</span>
						</div>
						<div>
							<span class="text-gray-500">{$i18n.t('Retry Count')}:</span>
							<span class="ml-2 font-medium dark:text-white">{selectedErrorTask.retry_count}</span>
						</div>
						<div>
							<span class="text-gray-500">{$i18n.t('Started')}:</span>
							<span class="ml-2 font-medium dark:text-white">{formatTime(selectedErrorTask.started_at)}</span>
						</div>
						<div>
							<span class="text-gray-500">{$i18n.t('Duration')}:</span>
							<span class="ml-2 font-medium dark:text-white">{formatDuration(selectedErrorTask.elapsed_seconds)}</span>
						</div>
					</div>
				</div>

				<!-- Error Message -->
				<div class="mb-4">
					<h4 class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{$i18n.t('Error Message')}</h4>
					<div class="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
						<pre class="text-sm text-red-700 dark:text-red-300 whitespace-pre-wrap break-words font-mono">{selectedErrorTask.error_message || $i18n.t('No error message available')}</pre>
					</div>
				</div>

				<!-- Progress Info -->
				{#if selectedErrorTask.total_chunks}
					<div class="mb-4">
						<h4 class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">{$i18n.t('Progress at Failure')}</h4>
						<div class="p-4 rounded-lg bg-gray-50 dark:bg-gray-800">
							<div class="flex items-center gap-4">
								<div class="flex-1">
									<div class="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
										<div
											class="h-full bg-red-500 transition-all duration-300"
											style="width: {selectedErrorTask.progress * 100}%"
										></div>
									</div>
								</div>
								<span class="text-sm text-gray-600 dark:text-gray-400">
									{selectedErrorTask.processed_chunks}/{selectedErrorTask.total_chunks} chunks ({Math.round(selectedErrorTask.progress * 100)}%)
								</span>
							</div>
						</div>
					</div>
				{/if}

				<!-- Actions -->
				<div class="flex justify-end gap-2 mt-6">
					{#if canRetry(selectedErrorTask)}
						<button
							class="px-4 py-2 text-sm font-medium rounded-lg bg-blue-500 text-white hover:bg-blue-600 transition"
							on:click={() => {
								if (selectedErrorTask) {
									handleRetry(selectedErrorTask);
								}
								closeErrorModal();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="w-4 h-4 inline-block mr-1"
							>
								<path
									fill-rule="evenodd"
									d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
									clip-rule="evenodd"
								/>
							</svg>
							{$i18n.t('Retry Task')}
						</button>
					{/if}
					<button
						class="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 transition"
						on:click={closeErrorModal}
					>
						{$i18n.t('Close')}
					</button>
				</div>
			</div>
		</Modal>
	{/if}
{/if}
