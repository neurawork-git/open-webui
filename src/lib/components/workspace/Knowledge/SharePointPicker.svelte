<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import {
		searchSharePointSites,
		type SharePointSiteSearchResult
	} from '$lib/apis/knowledge';
	import { openOneDrivePicker } from '$lib/utils/onedrive-file-picker';

	const i18n = getContext<any>('i18n');

	export let show = false;

	// Callbacks — one of these fires when the user confirms a selection.
	export let onSiteSelected: (siteId: string, siteName: string) => void = () => {};
	export let onFolderSelected: (driveId: string, itemId: string) => void = () => {};

	type Mode = 'site' | 'folder';
	let mode: Mode = 'site';

	let query = '';
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let searching = false;
	let results: SharePointSiteSearchResult[] = [];
	let searchError = '';
	let selectedSite: SharePointSiteSearchResult | null = null;

	const handleQueryInput = () => {
		selectedSite = null;
		if (debounceTimer) clearTimeout(debounceTimer);
		if (!query.trim()) {
			results = [];
			searchError = '';
			return;
		}
		debounceTimer = setTimeout(runSearch, 300);
	};

	const runSearch = async () => {
		const q = query.trim();
		if (!q) return;
		searching = true;
		searchError = '';
		try {
			results = await searchSharePointSites(localStorage.token, q);
		} catch (e: any) {
			searchError = typeof e === 'string' ? e : (e?.detail ?? `${e}`);
			results = [];
		} finally {
			searching = false;
		}
	};

	const confirmSiteImport = () => {
		if (!selectedSite) return;
		onSiteSelected(selectedSite.id, selectedSite.display_name || selectedSite.name);
		resetAndClose();
	};

	const pickFolderViaOneDrive = async () => {
		try {
			const result = await openOneDrivePicker('organizations', 'folders');
			const items = result?.items ?? [];
			if (items.length > 0) {
				const folder = items[0];
				onFolderSelected(folder.parentReference.driveId, folder.id);
				resetAndClose();
			}
		} catch (e: any) {
			toast.error(`${e?.message ?? e}`);
		}
	};

	const resetAndClose = () => {
		query = '';
		results = [];
		selectedSite = null;
		searchError = '';
		mode = 'site';
		show = false;
	};
</script>

<Modal bind:show size="md">
	<div class="flex flex-col px-6 py-5 gap-4">
		<div class="flex items-center justify-between">
			<div class="text-lg font-medium">{$i18n.t('Import from SharePoint')}</div>
			<button
				class="text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
				aria-label="Close"
				on:click={resetAndClose}
			>
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<div class="flex gap-1 text-sm border-b border-gray-200 dark:border-gray-700">
			<button
				class="px-3 py-2 {mode === 'site'
					? 'border-b-2 border-black dark:border-white font-medium'
					: 'text-gray-500'}"
				on:click={() => (mode = 'site')}
			>
				{$i18n.t('Whole site')}
			</button>
			<button
				class="px-3 py-2 {mode === 'folder'
					? 'border-b-2 border-black dark:border-white font-medium'
					: 'text-gray-500'}"
				on:click={() => (mode = 'folder')}
			>
				{$i18n.t('Specific folder')}
			</button>
		</div>

		{#if mode === 'site'}
			<div class="text-sm text-gray-600 dark:text-gray-400">
				{$i18n.t('Search for a SharePoint site. Importing a site pulls every file from all document libraries.')}
			</div>

			<div class="flex items-center gap-2 border border-gray-200 dark:border-gray-700 rounded-xl px-3 py-2">
				<Search className="w-4 h-4 text-gray-500" strokeWidth="2" />
				<input
					type="text"
					class="w-full bg-transparent outline-none text-sm"
					placeholder={$i18n.t('Site name or keyword…')}
					bind:value={query}
					on:input={handleQueryInput}
				/>
				{#if searching}
					<Spinner className="size-4" />
				{/if}
			</div>

			{#if searchError}
				<div class="text-sm text-red-500">{searchError}</div>
			{/if}

			{#if results.length > 0}
				<div class="max-h-80 overflow-y-auto flex flex-col gap-1">
					{#each results as site (site.id)}
						<button
							class="text-left px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 {selectedSite?.id === site.id
								? 'bg-gray-100 dark:bg-gray-800'
								: ''}"
							on:click={() => (selectedSite = site)}
						>
							<div class="text-sm font-medium">{site.display_name || site.name}</div>
							{#if site.web_url}
								<div class="text-xs text-gray-500 truncate">{site.web_url}</div>
							{/if}
						</button>
					{/each}
				</div>
			{:else if query.trim() && !searching && !searchError}
				<div class="text-sm text-gray-500">{$i18n.t('No sites match this query.')}</div>
			{/if}

			<div class="flex justify-end gap-2 pt-2">
				<button
					class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
					on:click={resetAndClose}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-2 text-sm rounded-xl bg-black text-white dark:bg-white dark:text-black disabled:opacity-50"
					disabled={!selectedSite}
					on:click={confirmSiteImport}
				>
					{$i18n.t('Import whole site')}
				</button>
			</div>
		{:else}
			<div class="text-sm text-gray-600 dark:text-gray-400">
				{$i18n.t('Opens the Microsoft folder picker. Pick a single folder; subfolders are imported recursively and their path becomes part of the filename.')}
			</div>

			<div class="flex justify-end gap-2 pt-2">
				<button
					class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
					on:click={resetAndClose}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-2 text-sm rounded-xl bg-black text-white dark:bg-white dark:text-black"
					on:click={pickFolderViaOneDrive}
				>
					{$i18n.t('Open folder picker')}
				</button>
			</div>
		{/if}
	</div>
</Modal>
