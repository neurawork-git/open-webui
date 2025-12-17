<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import Modal from './Modal.svelte';
	import Switch from './Switch.svelte';

	export let show = false;
	export let ragSettings: {
		top_k?: number | null;
		top_k_reranker?: number | null;
		relevance_threshold?: number | null;
		enable_hybrid_search?: boolean | null;
		enable_reranking?: boolean | null;
		hybrid_bm25_weight?: number | null;
		full_context?: boolean | null;
	} = {};

	// Local state for form
	let localSettings = { ...ragSettings };

	$: if (show) {
		// Reset local settings when modal opens
		localSettings = {
			top_k: ragSettings?.top_k ?? null,
			top_k_reranker: ragSettings?.top_k_reranker ?? null,
			relevance_threshold: ragSettings?.relevance_threshold ?? null,
			enable_hybrid_search: ragSettings?.enable_hybrid_search ?? null,
			enable_reranking: ragSettings?.enable_reranking ?? null,
			hybrid_bm25_weight: ragSettings?.hybrid_bm25_weight ?? null,
			full_context: ragSettings?.full_context ?? null
		};
	}

	const handleSave = () => {
		// Clean up null values that should remain as "use global"
		const cleanedSettings: typeof localSettings = {};

		if (localSettings.top_k !== null && localSettings.top_k !== undefined) {
			cleanedSettings.top_k = localSettings.top_k;
		}
		if (localSettings.top_k_reranker !== null && localSettings.top_k_reranker !== undefined) {
			cleanedSettings.top_k_reranker = localSettings.top_k_reranker;
		}
		if (localSettings.relevance_threshold !== null && localSettings.relevance_threshold !== undefined) {
			cleanedSettings.relevance_threshold = localSettings.relevance_threshold;
		}
		if (localSettings.enable_hybrid_search !== null && localSettings.enable_hybrid_search !== undefined) {
			cleanedSettings.enable_hybrid_search = localSettings.enable_hybrid_search;
		}
		if (localSettings.enable_reranking !== null && localSettings.enable_reranking !== undefined) {
			cleanedSettings.enable_reranking = localSettings.enable_reranking;
		}
		if (localSettings.hybrid_bm25_weight !== null && localSettings.hybrid_bm25_weight !== undefined) {
			cleanedSettings.hybrid_bm25_weight = localSettings.hybrid_bm25_weight;
		}
		if (localSettings.full_context !== null && localSettings.full_context !== undefined) {
			cleanedSettings.full_context = localSettings.full_context;
		}

		dispatch('save', cleanedSettings);
		show = false;
	};

	const handleReset = () => {
		localSettings = {
			top_k: null,
			top_k_reranker: null,
			relevance_threshold: null,
			enable_hybrid_search: null,
			enable_reranking: null,
			hybrid_bm25_weight: null,
			full_context: null
		};
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center">{$i18n.t('RAG Settings Override')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="px-5 pb-4">
			<div class="text-xs text-gray-500 mb-4">
				{$i18n.t('Override global RAG settings for this item. Leave empty to use global defaults.')}
			</div>

			<div class="flex flex-col gap-4">
				<!-- Top K -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Top K')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Number of chunks to retrieve')}</div>
					</div>
					<input
						type="number"
						class="w-20 px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
						min="1"
						max="50"
						placeholder="Global"
						bind:value={localSettings.top_k}
					/>
				</div>

				<!-- Top K Reranker -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Top K (Reranker)')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Results after reranking')}</div>
					</div>
					<input
						type="number"
						class="w-20 px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
						min="1"
						max="50"
						placeholder="Global"
						bind:value={localSettings.top_k_reranker}
					/>
				</div>

				<!-- Relevance Threshold -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Relevance Threshold')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Minimum score filter (0.0-1.0)')}</div>
					</div>
					<input
						type="number"
						class="w-20 px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
						min="0"
						max="1"
						step="0.05"
						placeholder="Global"
						bind:value={localSettings.relevance_threshold}
					/>
				</div>

				<!-- Hybrid BM25 Weight -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('BM25 Weight')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Hybrid search BM25 weight (0.0-1.0)')}</div>
					</div>
					<input
						type="number"
						class="w-20 px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
						min="0"
						max="1"
						step="0.1"
						placeholder="Global"
						bind:value={localSettings.hybrid_bm25_weight}
					/>
				</div>

				<!-- Enable Hybrid Search -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Hybrid Search')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Enable BM25+Vector hybrid search')}</div>
					</div>
					<div class="flex items-center gap-2">
						<select
							class="px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
							bind:value={localSettings.enable_hybrid_search}
						>
							<option value={null}>{$i18n.t('Global')}</option>
							<option value={true}>{$i18n.t('Enabled')}</option>
							<option value={false}>{$i18n.t('Disabled')}</option>
						</select>
					</div>
				</div>

				<!-- Enable Reranking -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Reranking')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Apply reranking model to results')}</div>
					</div>
					<div class="flex items-center gap-2">
						<select
							class="px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
							bind:value={localSettings.enable_reranking}
						>
							<option value={null}>{$i18n.t('Global')}</option>
							<option value={true}>{$i18n.t('Enabled')}</option>
							<option value={false}>{$i18n.t('Disabled')}</option>
						</select>
					</div>
				</div>

				<!-- Full Context -->
				<div class="flex justify-between items-center">
					<div class="flex flex-col">
						<div class="text-sm font-medium">{$i18n.t('Full Context')}</div>
						<div class="text-xs text-gray-500">{$i18n.t('Bypass retrieval, use full documents')}</div>
					</div>
					<div class="flex items-center gap-2">
						<select
							class="px-2 py-1 text-sm border rounded dark:bg-gray-800 dark:border-gray-700"
							bind:value={localSettings.full_context}
						>
							<option value={null}>{$i18n.t('Global')}</option>
							<option value={true}>{$i18n.t('Enabled')}</option>
							<option value={false}>{$i18n.t('Disabled')}</option>
						</select>
					</div>
				</div>
			</div>

			<div class="flex justify-between mt-6">
				<button
					class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
					on:click={handleReset}
				>
					{$i18n.t('Reset to Global')}
				</button>
				<div class="flex gap-2">
					<button
						class="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 rounded"
						on:click={() => {
							show = false;
						}}
					>
						{$i18n.t('Cancel')}
					</button>
					<button
						class="px-3 py-1.5 text-sm bg-black text-white dark:bg-white dark:text-black rounded hover:opacity-80"
						on:click={handleSave}
					>
						{$i18n.t('Save')}
					</button>
				</div>
			</div>
		</div>
	</div>
</Modal>
