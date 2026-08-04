<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import {
		listSharePointSites,
		listSharePointSiteDrives,
		listSharePointFolderChildren,
		type SharePointSiteSearchResult,
		type SharePointDriveSummary,
		type SharePointChildItem
	} from '$lib/apis/knowledge';

	const i18n = getContext<any>('i18n');

	export let show = false;
	export let onSiteSelected: (siteId: string, siteName: string) => void = () => {};
	export let onFolderSelected: (
		driveId: string,
		itemId: string,
		displayName: string
	) => void = () => {};

	// -- Sites pane state -------------------------------------------------------
	let sites: SharePointSiteSearchResult[] = [];
	let sitesNextLink: string | null = null;
	let sitesLoading = false;
	let sitesLoadingMore = false;
	let sitesError = '';
	let sitesFilter = '';
	let selectedSite: SharePointSiteSearchResult | null = null;

	// -- Drill-down pane state --------------------------------------------------
	type Crumb = {
		kind: 'site' | 'drive' | 'folder';
		label: string;
		siteId?: string;
		driveId?: string;
		driveName?: string;
		itemId?: string;
		size: number;
	};

	let breadcrumb: Crumb[] = [];
	let drives: SharePointDriveSummary[] = [];
	let folders: SharePointChildItem[] = [];
	let files: SharePointChildItem[] = [];
	let childrenNextLink: string | null = null;
	let paneLoading = false;
	let paneLoadingMore = false;
	let paneError = '';

	// -- Helpers ---------------------------------------------------------------
	const formatBytes = (bytes: number): string => {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		let v = bytes;
		let u = 0;
		while (v >= 1024 && u < units.length - 1) {
			v /= 1024;
			u++;
		}
		return `${v.toFixed(v < 10 && u > 0 ? 1 : 0)} ${units[u]}`;
	};

	const filteredSites = () => {
		const q = sitesFilter.trim().toLowerCase();
		if (!q) return sites;
		return sites.filter(
			(s) =>
				(s.display_name || '').toLowerCase().includes(q) ||
				(s.name || '').toLowerCase().includes(q) ||
				(s.web_url || '').toLowerCase().includes(q)
		);
	};

	const loadSitesInitial = async () => {
		sitesLoading = true;
		sitesError = '';
		try {
			const page = await listSharePointSites(localStorage.token, '*', null);
			sites = page.sites;
			sitesNextLink = page.next_link;
		} catch (e: any) {
			sitesError = typeof e === 'string' ? e : (e?.detail ?? `${e}`);
		} finally {
			sitesLoading = false;
		}
	};

	const loadMoreSites = async () => {
		if (!sitesNextLink || sitesLoadingMore) return;
		sitesLoadingMore = true;
		try {
			const page = await listSharePointSites(localStorage.token, '*', sitesNextLink);
			sites = [...sites, ...page.sites];
			sitesNextLink = page.next_link;
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (e?.detail ?? `${e}`));
		} finally {
			sitesLoadingMore = false;
		}
	};

	const selectSite = async (site: SharePointSiteSearchResult) => {
		selectedSite = site;
		breadcrumb = [
			{
				kind: 'site',
				label: site.display_name || site.name,
				siteId: site.id,
				size: 0
			}
		];
		drives = [];
		folders = [];
		files = [];
		childrenNextLink = null;
		paneLoading = true;
		paneError = '';
		try {
			const summary = await listSharePointSiteDrives(localStorage.token, site.id);
			drives = summary.drives;
			// propagate total size onto the breadcrumb root for display
			breadcrumb[0].size = drives.reduce((a, d) => a + (d.total_size || 0), 0);
		} catch (e: any) {
			paneError = typeof e === 'string' ? e : (e?.detail ?? `${e}`);
		} finally {
			paneLoading = false;
		}
	};

	const openDrive = async (drive: SharePointDriveSummary) => {
		breadcrumb = [
			...breadcrumb.filter((c) => c.kind === 'site'),
			{
				kind: 'drive',
				label: drive.name,
				driveId: drive.id,
				driveName: drive.name,
				itemId: drive.root_item_id,
				size: drive.total_size
			}
		];
		drives = [];
		folders = [];
		files = [];
		childrenNextLink = null;
		await loadChildren(drive.id, drive.root_item_id, null);
	};

	const openFolder = async (folder: SharePointChildItem) => {
		const current = breadcrumb[breadcrumb.length - 1];
		const driveId = current.driveId!;
		const driveName = current.driveName!;
		breadcrumb = [
			...breadcrumb,
			{
				kind: 'folder',
				label: folder.name,
				driveId,
				driveName,
				itemId: folder.id,
				size: folder.size
			}
		];
		drives = [];
		folders = [];
		files = [];
		childrenNextLink = null;
		await loadChildren(driveId, folder.id, null);
	};

	const loadChildren = async (driveId: string, itemId: string, nextLink: string | null) => {
		if (nextLink) paneLoadingMore = true;
		else paneLoading = true;
		paneError = '';
		try {
			const res = await listSharePointFolderChildren(localStorage.token, driveId, itemId, nextLink);
			if (!nextLink) {
				folders = res.folders;
				files = res.files;
			} else {
				folders = [...folders, ...res.folders];
				files = [...files, ...res.files];
			}
			childrenNextLink = res.next_link;
		} catch (e: any) {
			paneError = typeof e === 'string' ? e : (e?.detail ?? `${e}`);
		} finally {
			paneLoading = false;
			paneLoadingMore = false;
		}
	};

	const loadMoreChildren = async () => {
		if (!childrenNextLink) return;
		const current = breadcrumb[breadcrumb.length - 1];
		if (!current.driveId || !current.itemId) return;
		await loadChildren(current.driveId, current.itemId, childrenNextLink);
	};

	const jumpToCrumb = async (index: number) => {
		const target = breadcrumb[index];
		breadcrumb = breadcrumb.slice(0, index + 1);
		if (target.kind === 'site' && target.siteId) {
			// Re-load drives
			drives = [];
			folders = [];
			files = [];
			childrenNextLink = null;
			paneLoading = true;
			paneError = '';
			try {
				const summary = await listSharePointSiteDrives(localStorage.token, target.siteId);
				drives = summary.drives;
			} catch (e: any) {
				paneError = typeof e === 'string' ? e : (e?.detail ?? `${e}`);
			} finally {
				paneLoading = false;
			}
		} else if (target.driveId && target.itemId) {
			drives = [];
			folders = [];
			files = [];
			childrenNextLink = null;
			await loadChildren(target.driveId, target.itemId, null);
		}
	};

	// -- Import actions --------------------------------------------------------
	const confirmAndImportSite = () => {
		if (!selectedSite) return;
		const size = breadcrumb[0]?.size ?? 0;
		const ok = confirm(
			size > 0
				? $i18n.t('Import the entire site "{{site}}" ({{size}}) into this KB?', {
						site: selectedSite.display_name || selectedSite.name,
						size: formatBytes(size)
					})
				: $i18n.t('Import the entire site "{{site}}" into this KB?', {
						site: selectedSite.display_name || selectedSite.name
					})
		);
		if (!ok) return;
		onSiteSelected(selectedSite.id, selectedSite.display_name || selectedSite.name);
		resetAndClose();
	};

	const confirmAndImportCurrent = () => {
		const current = breadcrumb[breadcrumb.length - 1];
		if (!current) return;
		if (current.kind === 'site') {
			confirmAndImportSite();
			return;
		}
		if (!current.driveId || !current.itemId) return;
		const display = breadcrumb
			.filter((c) => c.kind !== 'site')
			.map((c) => c.label)
			.join(' › ');
		const ok = confirm(
			current.size > 0
				? $i18n.t('Import "{{path}}" ({{size}}) into this KB?', {
						path: display,
						size: formatBytes(current.size)
					})
				: $i18n.t('Import "{{path}}" into this KB?', { path: display })
		);
		if (!ok) return;
		onFolderSelected(current.driveId, current.itemId, display);
		resetAndClose();
	};

	const resetAndClose = () => {
		sites = [];
		sitesNextLink = null;
		sitesFilter = '';
		selectedSite = null;
		breadcrumb = [];
		drives = [];
		folders = [];
		files = [];
		childrenNextLink = null;
		sitesError = '';
		paneError = '';
		show = false;
	};

	// Load sites when modal opens
	$: if (show && sites.length === 0 && !sitesLoading && !sitesError) {
		loadSitesInitial();
	}

	$: currentLevel = breadcrumb[breadcrumb.length - 1];
	$: canImportCurrent =
		currentLevel &&
		(currentLevel.kind === 'site' || (!!currentLevel.driveId && !!currentLevel.itemId));
</script>

<Modal bind:show size="xl">
	<div class="flex flex-col h-[80vh]">
		<!-- Header -->
		<div
			class="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800"
		>
			<div class="flex flex-col">
				<div class="text-lg font-medium">{$i18n.t('Import from SharePoint')}</div>
				{#if breadcrumb.length > 0}
					<div class="text-xs text-gray-500 flex gap-1 mt-0.5">
						{#each breadcrumb as crumb, idx}
							<button
								class="hover:underline"
								class:font-medium={idx === breadcrumb.length - 1}
								on:click={() => jumpToCrumb(idx)}
							>
								{crumb.label}
							</button>
							{#if idx < breadcrumb.length - 1}
								<span class="text-gray-400">›</span>
							{/if}
						{/each}
					</div>
				{/if}
			</div>
			<button
				class="text-gray-500 hover:text-gray-900 dark:hover:text-gray-200"
				aria-label="Close"
				on:click={resetAndClose}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="w-5 h-5"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<!-- Two-pane body -->
		<div class="flex flex-1 overflow-hidden">
			<!-- Left: Sites -->
			<div class="w-72 border-r border-gray-200 dark:border-gray-800 flex flex-col">
				<div class="p-3 border-b border-gray-200 dark:border-gray-800">
					<div
						class="flex items-center gap-2 border border-gray-200 dark:border-gray-700 rounded-lg px-2 py-1.5"
					>
						<Search className="w-4 h-4 text-gray-500" strokeWidth="2" />
						<input
							type="text"
							class="w-full bg-transparent outline-none text-sm"
							placeholder={$i18n.t('Filter sites…')}
							bind:value={sitesFilter}
						/>
					</div>
				</div>

				<div class="flex-1 overflow-y-auto p-2">
					{#if sitesLoading}
						<div class="flex justify-center p-4"><Spinner /></div>
					{:else if sitesError}
						<div class="text-sm text-red-500 p-2">{sitesError}</div>
					{:else}
						{#each filteredSites() as site (site.id)}
							<button
								class="w-full text-left px-2 py-1.5 rounded-lg text-sm hover:bg-gray-50 dark:hover:bg-gray-800 {selectedSite?.id ===
								site.id
									? 'bg-gray-100 dark:bg-gray-800'
									: ''}"
								on:click={() => selectSite(site)}
							>
								<div class="font-medium truncate">{site.display_name || site.name}</div>
								{#if site.web_url}
									<div class="text-xs text-gray-500 truncate">{site.web_url}</div>
								{/if}
							</button>
						{/each}
						{#if filteredSites().length === 0 && sites.length > 0}
							<div class="text-sm text-gray-500 p-2">
								{$i18n.t('No sites match the filter.')}
							</div>
						{/if}
						{#if sites.length === 0}
							<div class="text-sm text-gray-500 p-2">
								{$i18n.t('No sites available.')}
							</div>
						{/if}
						{#if sitesNextLink}
							<button
								class="w-full mt-2 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
								disabled={sitesLoadingMore}
								on:click={loadMoreSites}
							>
								{sitesLoadingMore ? $i18n.t('Loading…') : $i18n.t('Load more sites')}
							</button>
						{/if}
					{/if}
				</div>
			</div>

			<!-- Right: Drill-down -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<div class="flex-1 overflow-y-auto p-3">
					{#if !selectedSite}
						<div class="text-sm text-gray-500 text-center mt-10">
							{$i18n.t('Pick a site on the left to browse its contents.')}
						</div>
					{:else if paneLoading}
						<div class="flex justify-center p-6"><Spinner /></div>
					{:else if paneError}
						<div class="text-sm text-red-500 p-2">{paneError}</div>
					{:else}
						<!-- Drives (shown when at site level) -->
						{#if drives.length > 0}
							<div class="text-xs uppercase text-gray-500 mb-2">
								{$i18n.t('Document libraries')}
							</div>
							<div class="flex flex-col gap-1">
								{#each drives as drive (drive.id)}
									<button
										class="text-left px-3 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center justify-between gap-3 border border-gray-100 dark:border-gray-800"
										on:click={() => openDrive(drive)}
									>
										<div class="flex items-center gap-2 min-w-0">
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 20 20"
												fill="currentColor"
												class="w-5 h-5 shrink-0 text-gray-500"
											>
												<path
													d="M3.75 3A1.75 1.75 0 0 0 2 4.75v10.5C2 16.216 2.784 17 3.75 17h12.5A1.75 1.75 0 0 0 18 15.25V7.75A1.75 1.75 0 0 0 16.25 6H10L8.72 4.72A1.75 1.75 0 0 0 7.48 4H3.75Z"
												/>
											</svg>
											<div class="truncate font-medium text-sm">{drive.name}</div>
										</div>
										<div class="text-xs text-gray-500 shrink-0">
											{#if drive.total_size > 0}
												{formatBytes(drive.total_size)}
											{/if}
										</div>
									</button>
								{/each}
							</div>
						{/if}

						<!-- Folders -->
						{#if folders.length > 0}
							<div class="text-xs uppercase text-gray-500 mt-4 mb-2">
								{$i18n.t('Folders')}
							</div>
							<div class="flex flex-col gap-1">
								{#each folders as folder (folder.id)}
									<button
										class="text-left px-3 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center justify-between gap-3 border border-gray-100 dark:border-gray-800"
										on:click={() => openFolder(folder)}
									>
										<div class="flex items-center gap-2 min-w-0">
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 20 20"
												fill="currentColor"
												class="w-5 h-5 shrink-0 text-gray-500"
											>
												<path
													d="M3.75 3A1.75 1.75 0 0 0 2 4.75v10.5C2 16.216 2.784 17 3.75 17h12.5A1.75 1.75 0 0 0 18 15.25V7.75A1.75 1.75 0 0 0 16.25 6H10L8.72 4.72A1.75 1.75 0 0 0 7.48 4H3.75Z"
												/>
											</svg>
											<div class="truncate font-medium text-sm">{folder.name}</div>
										</div>
										<div class="text-xs text-gray-500 shrink-0 flex items-center gap-3">
											<span>{folder.child_count} {$i18n.t('items')}</span>
											{#if folder.size > 0}
												<span>{formatBytes(folder.size)}</span>
											{/if}
										</div>
									</button>
								{/each}
							</div>
						{/if}

						<!-- Files (preview, not clickable) -->
						{#if files.length > 0}
							<div class="text-xs uppercase text-gray-500 mt-4 mb-2">
								{$i18n.t('Files in this folder')} ({files.length})
							</div>
							<div class="flex flex-col gap-0.5 text-sm">
								{#each files.slice(0, 25) as file (file.id)}
									<div
										class="px-3 py-1 flex justify-between items-center text-gray-600 dark:text-gray-400"
									>
										<div class="truncate">{file.name}</div>
										<div class="text-xs text-gray-500 shrink-0">
											{formatBytes(file.size)}
										</div>
									</div>
								{/each}
								{#if files.length > 25}
									<div class="px-3 py-1 text-xs text-gray-500">
										{$i18n.t('… and {{n}} more files at this level', { n: files.length - 25 })}
									</div>
								{/if}
							</div>
						{/if}

						{#if drives.length === 0 && folders.length === 0 && files.length === 0}
							<div class="text-sm text-gray-500 text-center mt-6">
								{$i18n.t('This folder is empty.')}
							</div>
						{/if}

						{#if childrenNextLink}
							<button
								class="w-full mt-4 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
								disabled={paneLoadingMore}
								on:click={loadMoreChildren}
							>
								{paneLoadingMore ? $i18n.t('Loading…') : $i18n.t('Load more items')}
							</button>
						{/if}
					{/if}
				</div>

				<!-- Footer -->
				<div
					class="border-t border-gray-200 dark:border-gray-800 p-3 flex items-center justify-between gap-3"
				>
					<div class="text-xs text-gray-500">
						{#if currentLevel}
							{currentLevel.kind === 'site'
								? $i18n.t('Entire site')
								: currentLevel.kind === 'drive'
									? $i18n.t('Entire drive')
									: $i18n.t('Current folder')}:
							<span class="font-medium">{formatBytes(currentLevel.size)}</span>
						{/if}
					</div>
					<div class="flex gap-2">
						<button
							class="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
							on:click={resetAndClose}
						>
							{$i18n.t('Cancel')}
						</button>
						<button
							class="px-4 py-2 text-sm rounded-lg bg-black text-white dark:bg-white dark:text-black disabled:opacity-40"
							disabled={!canImportCurrent}
							on:click={confirmAndImportCurrent}
						>
							{#if currentLevel?.kind === 'site'}
								{$i18n.t('Import entire site')}
							{:else if currentLevel?.kind === 'drive'}
								{$i18n.t('Import entire drive')}
							{:else}
								{$i18n.t('Import this folder')}
							{/if}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</Modal>
