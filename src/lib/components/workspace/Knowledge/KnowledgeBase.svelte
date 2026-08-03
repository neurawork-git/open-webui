<script lang="ts">
	import Fuse from 'fuse.js';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { onMount, getContext, onDestroy, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		mobile,
		showSidebar,
		knowledge as _knowledge,
		config,
		user,
		settings
	} from '$lib/stores';

	import {
		updateFileDataContentById,
		uploadFile,
		deleteFileById,
		getFileById,
		renameFileById
	} from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		getKnowledgeById,
		getKnowledgeBases,
		getPendingKnowledgeFiles,
		listSharePointFolder,
		listSharePointSiteFiles,
		importSharePointFile,
		persistSharePointSource,
		reimportSharePointFolder,
		reindexKnowledgeById,
		removeFileFromKnowledgeById,
		resetKnowledgeById,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		updateKnowledgeAccessGrants,
		searchKnowledgeFilesById,
		createKnowledgeDirectory,
		updateKnowledgeDirectory,
		deleteKnowledgeDirectory,
		moveFileInKnowledge,
		syncKnowledgeDiff,
		syncKnowledgeCleanup,
		testExternalKnowledgeRetrieval
	} from '$lib/apis/knowledge';
	import { processWeb, processYoutubeVideo } from '$lib/apis/retrieval';

	import { blobToFile, isYoutubeUrl, copyToClipboard } from '$lib/utils';
	import { computeFileHash } from '$lib/utils/hash';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';
	import NewDirectoryModal from './KnowledgeBase/NewDirectoryModal.svelte';
	import KnowledgeBreadcrumbs from './KnowledgeBase/KnowledgeBreadcrumbs.svelte';
	import SharePointPicker from './SharePointPicker.svelte';

	import SyncConfirmDialog from '../../common/ConfirmDialog.svelte';
	import ConfirmDialog from '../../common/ConfirmDialog.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import FileItemModal from '$lib/components/common/FileItemModal.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import RagSettingsModal from '$lib/components/common/RagSettingsModal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import FilesOverlay from '$lib/components/chat/MessageInput/FilesOverlay.svelte';
	import DropdownOptions from '$lib/components/common/DropdownOptions.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import AttachWebpageModal from '$lib/components/chat/MessageInput/AttachWebpageModal.svelte';

	let largeScreen = true;

	let pane;
	let showSidepanel = true;

	type RagSettings = {
		top_k?: number | null;
		top_k_reranker?: number | null;
		relevance_threshold?: number | null;
		enable_hybrid_search?: boolean | null;
		enable_reranking?: boolean | null;
		hybrid_bm25_weight?: number | null;
		full_context?: boolean | null;
	};

	let showAddWebpageModal = false;
	let showAddTextContentModal = false;
	let showNewDirectoryModal = false;

	let showSyncConfirmModal = false;
	let pendingSyncFiles: Array<{ path: string; filename: string; file: File }> | null = null;
	let syncing: string | null = null;
	let showAccessControlModal = false;
	let showResetConfirm = false;

	// Fork: SharePoint import / Reindex / per-KB RAG settings
	let showSharePointPicker = false;
	let sharePointImporting = false;
	let showReindexConfirmModal = false;
	let isReindexing = false;
	let showRagSettingsModal = false;
	let showFilePreview = false;

	let minSize = 0;
	type DirectoryFileEntry = { path: string; filename: string; file: File };
	type DirectoryManifestEntry = DirectoryFileEntry & { checksum: string; size: number };

	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids: string[];
		};
		files: any[];
		access_grants?: any[];
		write_access?: boolean;
		meta?: any;
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let knowledgeId = null;
	let isExternalKnowledge = false;

	let selectedFileId = null;
	let selectedFile = null;
	let selectedFileContent = '';
	let loadingFileContent = false;

	let inputFiles = null;

	let query = '';
	let includeContent = false;
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let viewOption = null;
	let sortKey = null;
	let direction = null;

	let currentPage = 1;
	let fileItems = null;
	let fileItemsTotal = null;

	// Directory state
	let currentDirectoryId: string | null = null;
	let directoryItems = [];
	let breadcrumbs = [];

	let showDeleteDirectoryConfirm = false;
	let pendingDeleteDirectoryId: string | null = null;
	let deleteDirectoryContents = true;

	let pendingPollTimer: ReturnType<typeof setInterval> | null = null;
	let externalTestQuery = '';
	let externalTestResult: {
		documents?: string[];
		metadatas?: Record<string, any>[];
		distances?: number[];
	} | null = null;

	$: isExternalKnowledge = knowledge?.meta?.source === 'external';

	const reset = () => {
		currentPage = 1;
	};

	const init = async () => {
		reset();
		await getItemsPage();
	};

	const handleSearchInput = () => {
		clearTimeout(searchDebounceTimer);

		searchDebounceTimer = setTimeout(() => {
			if (currentPage !== 1) {
				currentPage = 1;
			} else {
				getItemsPage();
			}
		}, 300);
	};

	// Immediate response to filter/pagination changes
	$: if (
		knowledgeId !== null &&
		viewOption !== undefined &&
		sortKey !== undefined &&
		direction !== undefined &&
		currentPage !== undefined &&
		includeContent !== undefined
	) {
		getItemsPage();
	}

	const getItemsPage = async () => {
		if (knowledgeId === null) return;

		// Flicker fix (commit 98cff8eb2): only show the loading spinner on the
		// initial load. On refreshes (e.g. per-file SharePoint import, pending-file
		// polling) keep the current list visible so the whole file list does not
		// flash empty on every re-fetch.
		if (fileItems === null) {
			fileItemsTotal = null;
		}

		if (sortKey === null) {
			direction = null;
		}

		const res = await searchKnowledgeFilesById(
			localStorage.token,
			knowledge.id,
			query,
			viewOption,
			sortKey,
			direction,
			currentPage,
			currentDirectoryId,
			includeContent
		).catch(() => {
			return null;
		});

		if (res) {
			fileItems = res.items;
			fileItemsTotal = res.total;
			directoryItems = res.directories ?? [];
			breadcrumbs = res.breadcrumbs ?? [];

			// Merge in-flight files not yet linked to the knowledge base
			try {
				const pendingFiles = await getPendingKnowledgeFiles(localStorage.token, knowledgeId);
				if (pendingFiles && pendingFiles.length > 0) {
					const existingIds = new Set(fileItems.map((f) => f.id));
					const newPending = pendingFiles
						.filter((f) => !existingIds.has(f.id))
						.map((f) => ({
							...f,
							name: f.meta?.name ?? f.filename,
							status: 'uploading'
						}));
					if (newPending.length > 0) {
						fileItems = [...newPending, ...fileItems];

						// Start polling for completion (if not already polling)
						if (!pendingPollTimer) {
							pendingPollTimer = setInterval(async () => {
								try {
									const still = await getPendingKnowledgeFiles(localStorage.token, knowledgeId);
									if (!still || still.length === 0) {
										clearInterval(pendingPollTimer);
										pendingPollTimer = null;
										init();
									}
								} catch {}
							}, 5000);
						}
					}
				}
			} catch (e) {
				console.warn('Failed to fetch pending files:', e);
			}
		}

		return res;
	};

	const fileSelectHandler = async (file) => {
		selectedFile = file;
		selectedFileContent = file?.data?.content ?? '';
		loadingFileContent = false;

		if (!file?.id || file?.data?.content !== undefined) {
			return;
		}

		loadingFileContent = true;
		try {
			const fileWithContent = await getFileById(localStorage.token, file.id);
			if (selectedFileId === file.id) {
				selectedFile = fileWithContent ?? file;
				selectedFileContent = fileWithContent?.data?.content ?? '';
			}
		} catch (e) {
			if (selectedFileId === file.id) {
				toast.error($i18n.t('Failed to load file content.'));
			}
		} finally {
			if (selectedFileId === file.id) {
				loadingFileContent = false;
			}
		}
	};

	const externalTestHandler = async () => {
		if (!isExternalKnowledge || !externalTestQuery.trim()) return;

		const external = knowledge?.meta?.external ?? {};
		const res = await testExternalKnowledgeRetrieval(localStorage.token, external.connection_id, {
			query: externalTestQuery,
			source: external.source,
			count: 5
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			externalTestResult = res;
		}
	};

	const createFileFromText = (name, content) => {
		const blob = new Blob([content], { type: 'text/plain' });
		const file = blobToFile(blob, `${name}.txt`);

		console.log(file);
		return file;
	};

	const uploadWeb = async (urls) => {
		if (!Array.isArray(urls)) {
			urls = [urls];
		}

		const newFileItems = urls.map((url) => ({
			type: 'file',
			file: '',
			id: null,
			url: url,
			name: url,
			size: null,
			status: 'uploading',
			error: '',
			itemId: uuidv4()
		}));

		// Display all items at once
		fileItems = [...newFileItems, ...(fileItems ?? [])];

		for (const fileItem of newFileItems) {
			try {
				console.log(fileItem);
				const res = await processWeb(localStorage.token, '', fileItem.url, false).catch((e) => {
					console.error('Error processing web URL:', e);
					return null;
				});

				if (res) {
					console.log(res);
					const file = createFileFromText(
						// Use URL as filename, sanitized
						fileItem.url
							.replace(/[^a-z0-9]/gi, '_')
							.toLowerCase()
							.slice(0, 50),
						res.content
					);

					const uploadedFile = await uploadFile(localStorage.token, file, {
						knowledge_id: knowledge.id,
						directory_id: currentDirectoryId
					}).catch((e) => {
						toast.error(`${e}`);
						return null;
					});

					if (uploadedFile) {
						console.log(uploadedFile);
						fileItems = fileItems.map((item) => {
							if (item.itemId === fileItem.itemId) {
								item.id = uploadedFile.id;
							}
							return item;
						});

						if (uploadedFile.error) {
							console.warn('File upload warning:', uploadedFile.error);
							toast.warning(uploadedFile.error);
							fileItems = fileItems.filter((file) => file.id !== uploadedFile.id);
						} else {
							toast.success($i18n.t('File added successfully.'));
							init();
						}
					} else {
						toast.error($i18n.t('Failed to upload file.'));
					}
				} else {
					// remove the item from fileItems
					fileItems = fileItems.filter((item) => item.itemId !== fileItem.itemId);
					toast.error($i18n.t('Failed to process URL: {{url}}', { url: fileItem.url }));
				}
			} catch (e) {
				// remove the item from fileItems
				fileItems = fileItems.filter((item) => item.itemId !== fileItem.itemId);
				toast.error(`${e}`);
			}
		}
	};

	const uploadFileHandler = async (file) => {
		console.log(file);

		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: uuidv4()
		};

		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			console.log('File exceeds max size limit:', {
				fileSize: file.size,
				maxSize: ($config?.file?.max_size ?? 0) * 1024 * 1024
			});
			toast.error(
				$i18n.t(`File size should not exceed {{maxSize}} MB.`, {
					maxSize: $config?.file?.max_size
				})
			);
			return;
		}

		fileItems = [fileItem, ...(fileItems ?? [])];
		try {
			let metadata = {
				knowledge_id: knowledge.id,
				directory_id: currentDirectoryId,
				// If the file is an audio file, provide the language for STT.
				...((file.type.startsWith('audio/') || file.type.startsWith('video/')) &&
				$settings?.audio?.stt?.language
					? {
							language: $settings?.audio?.stt?.language
						}
					: {})
			};

			const uploadedFile = await uploadFile(localStorage.token, file, metadata).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (uploadedFile) {
				console.log(uploadedFile);
				fileItems = fileItems.map((item) => {
					if (item.itemId === fileItem.itemId) {
						item.id = uploadedFile.id;
					}
					return item;
				});

				if (uploadedFile.error) {
					console.warn('File upload warning:', uploadedFile.error);
					toast.warning(uploadedFile.error);
					fileItems = fileItems.filter((file) => file.id !== uploadedFile.id);
				} else {
					toast.success($i18n.t('File added successfully.'));
					init();
				}
			} else {
				toast.error($i18n.t('Failed to upload file.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const uploadDirectoryHandler = async () => {
		const entries = await collectDirectoryFiles();
		if (entries?.length) {
			await uploadDirectoryEntries(entries);
		}
	};

	// Helper function to check if a path contains hidden folders
	const hasHiddenFolder = (path) => {
		return path.split('/').some((part) => part.startsWith('.'));
	};

	// Error handler
	const handleUploadError = (error) => {
		if (error.name === 'AbortError') {
			toast.info($i18n.t('Directory selection was cancelled'));
		} else {
			toast.error($i18n.t('Error accessing directory'));
			console.error('Directory access error:', error);
		}
	};

	// Collect files from a directory without uploading.
	const collectDirectoryFiles = async (): Promise<DirectoryFileEntry[] | null> => {
		const isFileSystemAccessSupported = 'showDirectoryPicker' in window;

		try {
			if (isFileSystemAccessSupported) {
				const dirHandle = await window.showDirectoryPicker();
				const collected: DirectoryFileEntry[] = [];

				async function traverse(handle: FileSystemDirectoryHandle, dirPath = '') {
					for await (const entry of handle.values()) {
						if (entry.name.startsWith('.')) continue;
						const entryPath = dirPath ? `${dirPath}/${entry.name}` : entry.name;
						if (hasHiddenFolder(entryPath)) continue;

						if (entry.kind === 'file') {
							const file = await entry.getFile();
							collected.push({ path: dirPath, filename: entry.name, file });
						} else if (entry.kind === 'directory') {
							await traverse(entry, entryPath);
						}
					}
				}

				await traverse(dirHandle, dirHandle.name);
				return collected;
			} else {
				// Firefox fallback
				return new Promise((resolve, reject) => {
					const input = document.createElement('input');
					input.type = 'file';
					input.webkitdirectory = true;
					input.directory = true;
					input.multiple = true;
					input.style.display = 'none';
					document.body.appendChild(input);

					input.onchange = () => {
						try {
							const files = Array.from(input.files || []).filter(
								(file) => !hasHiddenFolder(file.webkitRelativePath) && !file.name.startsWith('.')
							);

							const collected = files.map((file) => {
								const parts = file.webkitRelativePath.split('/');
								const filename = parts.pop() || file.name;
								const path = parts.join('/');
								return { path, filename, file };
							});

							document.body.removeChild(input);
							resolve(collected);
						} catch (error) {
							document.body.removeChild(input);
							reject(error);
						}
					};

					input.onerror = (error) => {
						document.body.removeChild(input);
						reject(error);
					};

					input.click();
				});
			}
		} catch (error) {
			handleUploadError(error);
			return null;
		}
	};

	const buildDirectoryManifest = async (
		entries: DirectoryFileEntry[]
	): Promise<DirectoryManifestEntry[]> => {
		return Promise.all(
			entries.map(async (entry) => ({
				...entry,
				checksum: await computeFileHash(entry.file),
				size: entry.file.size
			}))
		);
	};

	const createMissingDirectories = async (diff: any) => {
		if (!knowledge) return {};

		const directoryIdByPath: Record<string, string> = { ...(diff.directory_map || {}) };

		for (const dirPath of diff.mkdir) {
			const segments = dirPath.split('/');
			const name = segments.at(-1)!;
			const parentPath = segments.slice(0, -1).join('/');
			const parentId = parentPath ? directoryIdByPath[parentPath] : null;

			const directory = await createKnowledgeDirectory(
				localStorage.token,
				knowledge.id,
				name,
				parentId
			);
			if (directory) {
				directoryIdByPath[dirPath] = directory.id;
			}
		}

		return directoryIdByPath;
	};

	const getDirectoryUploadPath = (path: string) => {
		const currentPath = breadcrumbs.map((crumb) => crumb.name).join('/');
		return currentPath && path ? `${currentPath}/${path}` : currentPath || path;
	};

	const uploadDirectoryEntries = async (entries: DirectoryFileEntry[]) => {
		if (!knowledge) return;

		try {
			syncing = $i18n.t('Computing checksums ({{count}} files)', { count: entries.length });
			const manifest = await buildDirectoryManifest(entries);

			syncing = $i18n.t('Comparing with knowledge base...');
			const diff = await syncKnowledgeDiff(
				localStorage.token,
				id,
				manifest.map(({ filename, path, checksum, size }) => ({
					filename,
					path: getDirectoryUploadPath(path),
					checksum,
					size
				}))
			);

			if (!diff) {
				toast.error($i18n.t('Failed to compare files.'));
				return;
			}

			const directoryIdByPath = await createMissingDirectories(diff);

			let uploadedCount = 0;
			for (const entry of manifest) {
				uploadedCount++;
				const displayPath = entry.path ? `${entry.path}/${entry.filename}` : entry.filename;
				syncing = $i18n.t('Uploading {{current}}/{{total}}: {{file}}', {
					current: uploadedCount,
					total: manifest.length,
					file: displayPath
				});

				const fileObject = new File([entry.file], entry.filename, { type: entry.file.type });
				await uploadFile(localStorage.token, fileObject, {
					knowledge_id: knowledge.id,
					file_hash: entry.checksum,
					directory_id: entry.path
						? directoryIdByPath[getDirectoryUploadPath(entry.path)]
						: currentDirectoryId
				}).catch((e) => {
					toast.error(`${e}`);
					return null;
				});
			}

			toast.success($i18n.t('File uploaded successfully'));
			init();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			syncing = null;
		}
	};

	// Incremental sync: hash locally → diff on server → upload only what changed
	const syncDirectoryHandler = async () => {
		if (!pendingSyncFiles?.length) return;

		try {
			// ── 2. Compute checksums ──
			syncing = $i18n.t('Computing checksums ({{count}} files)', {
				count: pendingSyncFiles.length
			});
			const manifest = await buildDirectoryManifest(pendingSyncFiles);
			pendingSyncFiles = null;

			// ── 3. Diff against knowledge base ──
			syncing = $i18n.t('Comparing with knowledge base...');
			const diff = await syncKnowledgeDiff(
				localStorage.token,
				id,
				manifest.map(({ filename, path, checksum, size }) => ({ filename, path, checksum, size }))
			);

			if (!diff) {
				toast.error($i18n.t('Failed to compare files.'));
				return;
			}

			// ── 4. Cleanup — remove deleted + stale modified files first ──
			const staleFileIds = [
				...diff.deleted.map((d: any) => d.file_id),
				...diff.modified.map((m: any) => m.stale_file_id)
			];

			if (staleFileIds.length > 0 || diff.rmdir.length > 0) {
				syncing = $i18n.t('Removing {{count}} stale files...', { count: staleFileIds.length });
				await syncKnowledgeCleanup(localStorage.token, id, staleFileIds, diff.rmdir);
			}

			// ── 5. mkdir — create missing directories (parents first) ──
			const directoryIdByPath = await createMissingDirectories(diff);

			// ── 6. Upload added + modified files ──
			const filesToUpload = manifest.filter(
				(entry) =>
					diff.added.some((a: any) => a.filename === entry.filename && a.path === entry.path) ||
					diff.modified.some((m: any) => m.filename === entry.filename && m.path === entry.path)
			);

			let uploadedCount = 0;
			for (const entry of filesToUpload) {
				uploadedCount++;
				const displayPath = entry.path ? `${entry.path}/${entry.filename}` : entry.filename;
				syncing = $i18n.t('Uploading {{current}}/{{total}}: {{file}}', {
					current: uploadedCount,
					total: filesToUpload.length,
					file: displayPath
				});

				const fileObject = new File([entry.file], entry.filename, { type: entry.file.type });
				await uploadFile(localStorage.token, fileObject, {
					knowledge_id: knowledge.id,
					file_hash: entry.checksum,
					directory_id: entry.path ? directoryIdByPath[entry.path] : null
				}).catch(() => null);
			}

			// ── 7. Report ──
			toast.success(
				$i18n.t(
					'Sync complete: {{added}} added, {{modified}} modified, {{deleted}} deleted, {{unmodified}} unmodified',
					{
						added: diff.added.length,
						modified: diff.modified.length,
						deleted: diff.deleted.length,
						unmodified: diff.unmodified_count
					}
				)
			);
			init();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			syncing = null;
		}
	};

	// ── SharePoint import (fork) ──────────────────────────────────────────────
	const runSharePointPerFileImport = async (
		listing: Awaited<ReturnType<typeof listSharePointFolder>>,
		label: string
	) => {
		if (!knowledge) return;

		const files = listing.files ?? [];
		const total = files.length;

		if (total === 0) {
			toast.info($i18n.t('{{label}} has no importable files', { label }));
			return;
		}

		if (listing.truncated) {
			toast.warning(
				$i18n.t(
					'{{label}} too large — stopped after {{count}} files. Split into smaller folders and re-import.',
					{ label, count: total }
				)
			);
		}

		let imported = 0;
		let failed = 0;
		const progressToastId = `sharepoint-progress-${knowledge.id}`;
		const updateProgress = () => {
			const done = imported + failed;
			const percentage = (done / total) * 100;
			toast.info(
				$i18n.t('Upload Progress: {{uploadedFiles}}/{{totalFiles}} ({{percentage}}%)', {
					uploadedFiles: done,
					totalFiles: total,
					percentage: percentage.toFixed(0)
				}),
				{ id: progressToastId }
			);
		};

		updateProgress();

		for (const file of files) {
			try {
				await importSharePointFile(
					localStorage.token,
					knowledge.id,
					file.drive_id,
					file.item_id,
					file.path
				);
				imported++;
			} catch (e) {
				failed++;
				console.error('SharePoint per-file import failed', file.display_name, e);
				toast.error(
					$i18n.t('Failed to import "{{file}}": {{error}}', {
						file: file.display_name,
						error: typeof e === 'string' ? e : ((e as Error)?.message ?? 'unknown')
					})
				);
			}
			updateProgress();
		}

		// Single refresh after all files are processed — avoids per-file
		// null-flash that caused the list to flicker on every import.
		await getItemsPage();

		toast.dismiss(progressToastId);

		if (imported > 0) {
			toast.success(
				$i18n.t('Imported {{count}} files from "{{folder}}"', {
					count: imported,
					folder: listing.folder_name
				})
			);
			if (listing.source) {
				await persistSharePointSource(localStorage.token, knowledge.id, listing.source);
				knowledge = await getKnowledgeById(localStorage.token, id);
			}
		}
		if (failed > 0) {
			toast.warning($i18n.t('{{count}} files failed to import', { count: failed }));
		}
	};

	const sharePointSiteImportHandler = async (siteId: string, siteName: string) => {
		if (!knowledge) return;
		sharePointImporting = true;

		try {
			const listing = await listSharePointSiteFiles(localStorage.token, knowledge.id, siteId);
			await runSharePointPerFileImport(listing, listing.folder_name || siteName);
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			sharePointImporting = false;
		}
	};

	const sharePointImportHandler = async (driveId: string, itemId: string) => {
		if (!knowledge) return;
		sharePointImporting = true;

		try {
			const listing = await listSharePointFolder(localStorage.token, knowledge.id, driveId, itemId);
			await runSharePointPerFileImport(listing, listing.folder_name);
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			sharePointImporting = false;
		}
	};

	const sharePointReimportHandler = async () => {
		if (!knowledge) return;
		sharePointImporting = true;

		try {
			const result = await reimportSharePointFolder(localStorage.token, knowledge.id);

			if (result) {
				if (result.imported > 0) {
					toast.success(
						$i18n.t('Re-imported {{count}} files from "{{folder}}"', {
							count: result.imported,
							folder: result.folder_name
						})
					);
				}
				if (result.failed > 0) {
					toast.warning($i18n.t('{{count}} files failed to import', { count: result.failed }));
				}
				if (result.truncated) {
					toast.warning(
						$i18n.t(
							'Folder too large — stopped after {{count}} files. Split into smaller folders and re-import.',
							{ count: result.total_files }
						)
					);
				}
				await getItemsPage();
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			sharePointImporting = false;
		}
	};

	// ── Reindex (fork) ────────────────────────────────────────────────────────
	const reindexHandler = async () => {
		isReindexing = true;
		try {
			const res = await reindexKnowledgeById(localStorage.token, id);
			if (res && res.success) {
				toast.success(
					$i18n.t('Reindex completed: {{processed}}/{{total}} files processed', {
						processed: res.processed_files,
						total: res.total_files
					})
				);
				if (res.failed_files && res.failed_files.length > 0) {
					toast.warning(
						$i18n.t('{{count}} files failed to reindex', { count: res.failed_files.length })
					);
				}
				// Refresh the knowledge base data
				knowledge = await getKnowledgeById(localStorage.token, id);
				_knowledge.set(await getKnowledgeBases(localStorage.token));
			} else {
				toast.error($i18n.t('Reindex failed'));
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			isReindexing = false;
		}
	};

	const addFileHandler = async (fileId) => {
		const res = await addFileToKnowledgeById(
			localStorage.token,
			id,
			fileId,
			currentDirectoryId
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('File added successfully.'));
			init();
		} else {
			toast.error($i18n.t('Failed to add file.'));
			fileItems = fileItems.filter((file) => file.id !== fileId);
		}
	};

	// Directory handlers
	const navigateToDirectory = (directoryId: string | null) => {
		currentDirectoryId = directoryId;
		currentPage = 1;
		selectedFileId = null;
		selectedFile = null;
		selectedFileContent = '';
		loadingFileContent = false;
		getItemsPage();
	};

	const createDirectoryHandler = async (name: string) => {
		const res = await createKnowledgeDirectory(
			localStorage.token,
			knowledge.id,
			name,
			currentDirectoryId
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Directory created.'));
			getItemsPage();
		}
	};

	const renameDirectoryHandler = async (dirId: string, name: string) => {
		const res = await updateKnowledgeDirectory(localStorage.token, knowledge.id, dirId, {
			name
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Directory renamed.'));
			getItemsPage();
		}
	};

	const confirmDeleteDirectory = (dirId: string) => {
		pendingDeleteDirectoryId = dirId;
		showDeleteDirectoryConfirm = true;
	};

	const deleteDirectoryHandler = async (moveFiles: boolean) => {
		if (!pendingDeleteDirectoryId) return;

		const res = await deleteKnowledgeDirectory(
			localStorage.token,
			knowledge.id,
			pendingDeleteDirectoryId,
			moveFiles
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Directory deleted.'));
			getItemsPage();
		}
		pendingDeleteDirectoryId = null;
	};

	const moveFileToDirectoryHandler = async (fileId: string, directoryId: string | null) => {
		const res = await moveFileInKnowledge(
			localStorage.token,
			knowledge.id,
			fileId,
			directoryId
		).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('File moved.'));
			getItemsPage();
		}
	};

	const moveDirectoryHandler = async (dirId: string, targetParentId: string | null) => {
		if (dirId === targetParentId) return;
		const res = await updateKnowledgeDirectory(localStorage.token, knowledge.id, dirId, {
			parent_id: targetParentId
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Directory moved.'));
			getItemsPage();
		}
	};

	const deleteFileHandler = async (fileId) => {
		try {
			console.log('Starting file deletion process for:', fileId);

			// Remove from knowledge base only
			const res = await removeFileFromKnowledgeById(localStorage.token, id, fileId);
			console.log('Knowledge base updated:', res);

			if (res) {
				toast.success($i18n.t('File removed successfully.'));
				await init();
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error(`${e}`);
		}
	};

	const renameFileHandler = async (fileId: string, name: string) => {
		try {
			const res = await renameFileById(localStorage.token, fileId, name);
			if (res) {
				toast.success($i18n.t('File renamed.'));
				getItemsPage();
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	let debounceTimeout = null;
	let mediaQuery;

	let dragged = false;
	let isSaving = false;

	const updateFileContentHandler = async () => {
		if (isSaving || loadingFileContent || !selectedFile?.id) {
			return;
		}

		isSaving = true;

		try {
			const res = await updateFileDataContentById(
				localStorage.token,
				selectedFile.id,
				selectedFileContent
			).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (res) {
				toast.success($i18n.t('File content updated successfully.'));

				selectedFileId = null;
				selectedFile = null;
				selectedFileContent = '';

				await init();
			}
		} finally {
			isSaving = false;
		}
	};

	const changeDebounceHandler = () => {
		console.log('debounce');
		if (debounceTimeout) {
			clearTimeout(debounceTimeout);
		}

		debounceTimeout = setTimeout(async () => {
			if (knowledge.name.trim() === '' || knowledge.description.trim() === '') {
				toast.error($i18n.t('Please fill in all fields.'));
				return;
			}

			const res = await updateKnowledgeById(localStorage.token, id, {
				...knowledge,
				name: knowledge.name,
				description: knowledge.description,
				access_grants: knowledge.access_grants ?? []
			}).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				toast.success($i18n.t('Knowledge updated successfully'));
			}
		}, 1000);
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
		} else {
			largeScreen = false;
		}
	};

	const readDirectoryEntries = async (reader: any) => {
		const entries: any[] = [];

		while (true) {
			const batch = await new Promise<any[]>((resolve, reject) => {
				reader.readEntries(resolve, reject);
			});

			if (batch.length === 0) {
				break;
			}

			entries.push(...batch);
		}

		return entries;
	};

	const collectDroppedEntryFiles = async (
		entry: any,
		entryPath = entry.name
	): Promise<DirectoryFileEntry[]> => {
		if (entry.name.startsWith('.') || hasHiddenFolder(entryPath)) {
			return [];
		}

		if (entry.isFile) {
			const file = await new Promise<File>((resolve, reject) => {
				entry.file(resolve, reject);
			});
			const parts = entryPath.split('/');
			const filename = parts.pop() || file.name;
			return [{ path: parts.join('/'), filename, file }];
		}

		if (entry.isDirectory) {
			const reader = entry.createReader();
			const entries = await readDirectoryEntries(reader);
			const nested = await Promise.all(
				entries.map((child) => collectDroppedEntryFiles(child, `${entryPath}/${child.name}`))
			);
			return nested.flat();
		}

		return [];
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		dragged = false;

		if (!knowledge?.write_access) {
			toast.error($i18n.t('You do not have permission to upload files to this knowledge base.'));
			return;
		}

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const inputItems = e.dataTransfer?.items;

				if (inputItems && inputItems.length > 0) {
					const directoryEntries: DirectoryFileEntry[] = [];
					const looseFiles: File[] = [];

					for (const rawItem of Array.from(inputItems)) {
						const item = rawItem as DataTransferItem & { webkitGetAsEntry?: () => any };
						const entry = item.webkitGetAsEntry?.();

						if (entry?.isDirectory) {
							directoryEntries.push(...(await collectDroppedEntryFiles(entry)));
						} else {
							const file = item.getAsFile();
							if (file) {
								looseFiles.push(file);
							}
						}
					}

					for (const file of looseFiles) {
						await uploadFileHandler(file);
					}

					if (directoryEntries.length > 0) {
						await uploadDirectoryEntries(directoryEntries);
					}
				} else {
					toast.error($i18n.t(`File not found.`));
				}
			}
		}
	};

	onMount(async () => {
		// listen to resize 1024px
		mediaQuery = window.matchMedia('(min-width: 1024px)');

		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		// Select the container element you want to observe
		const container = document.getElementById('collection-container');

		// initialize the minSize based on the container width
		minSize = !largeScreen ? 100 : Math.floor((300 / container.clientWidth) * 100);

		// Create a new ResizeObserver instance
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				// calculate the percentage of 300
				const percentage = (300 / width) * 100;
				// set the minSize to the percentage, must be an integer
				minSize = !largeScreen ? 100 : Math.floor(percentage);

				if (showSidepanel) {
					if (pane && pane.isExpanded() && pane.getSize() < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		// Start observing the container's size changes
		resizeObserver.observe(container);

		if (pane) {
			pane.expand();
		}

		id = $page.params.id;
		const res = await getKnowledgeById(localStorage.token, id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			knowledge = res;
			if (!Array.isArray(knowledge?.access_grants)) {
				knowledge.access_grants = [];
			}
			knowledgeId = knowledge?.id;
		} else {
			goto('/workspace/knowledge');
		}

		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
		if (pendingPollTimer) {
			clearInterval(pendingPollTimer);
			pendingPollTimer = null;
		}
		mediaQuery?.removeEventListener('change', handleMediaQuery);
		const dropZone = document.querySelector('body');
		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);
	});

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	};
</script>

<FilesOverlay show={dragged} />

<SharePointPicker
	bind:show={showSharePointPicker}
	onSiteSelected={(siteId, siteName) => sharePointSiteImportHandler(siteId, siteName)}
	onFolderSelected={(driveId, itemId) => sharePointImportHandler(driveId, itemId)}
/>

<SyncConfirmDialog
	bind:show={showSyncConfirmModal}
	message={$i18n.t(
		'{{count}} files selected. Only new and modified files will be uploaded. Deleted files will be removed. The folder structure will be mirrored. Continue?',
		{ count: pendingSyncFiles?.length ?? 0 }
	)}
	on:confirm={() => {
		syncDirectoryHandler();
	}}
	on:cancel={() => {
		pendingSyncFiles = null;
	}}
/>

<SyncConfirmDialog
	bind:show={showReindexConfirmModal}
	message={$i18n.t(
		'This will delete and re-create all vector embeddings for this knowledge base. This may take a while for large collections. Do you wish to continue?'
	)}
	on:confirm={() => {
		reindexHandler();
	}}
/>

<AttachWebpageModal
	bind:show={showAddWebpageModal}
	onSubmit={async (e) => {
		uploadWeb(e.data);
	}}
/>

<AddTextContentModal
	bind:show={showAddTextContentModal}
	on:submit={(e) => {
		const file = createFileFromText(e.detail.name, e.detail.content);
		uploadFileHandler(file);
	}}
/>

<NewDirectoryModal
	bind:show={showNewDirectoryModal}
	on:submit={(e) => {
		createDirectoryHandler(e.detail.name);
	}}
/>

<input
	id="files-input"
	bind:files={inputFiles}
	type="file"
	multiple
	hidden
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			for (const file of inputFiles) {
				await uploadFileHandler(file);
			}

			inputFiles = null;
			const fileInputElement = document.getElementById('files-input');

			if (fileInputElement) {
				fileInputElement.value = '';
			}
		} else {
			toast.error($i18n.t(`File not found.`));
		}
	}}
/>

<div class="flex flex-col w-full h-full min-h-full" id="collection-container">
	{#if id && knowledge}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessGrants={knowledge.access_grants}
			share={$user?.permissions?.sharing?.knowledge || $user?.role === 'admin'}
			sharePublic={$user?.permissions?.sharing?.public_knowledge || $user?.role === 'admin'}
			shareUsers={($user?.permissions?.access_grants?.allow_users ?? true) ||
				$user?.role === 'admin'}
			onChange={async () => {
				try {
					await updateKnowledgeAccessGrants(localStorage.token, id, knowledge.access_grants ?? []);
					toast.success($i18n.t('Saved'));
				} catch (error) {
					toast.error(`${error}`);
				}
			}}
			accessRoles={['read', 'write']}
		/>
		{#if !isExternalKnowledge}
			<RagSettingsModal
				bind:show={showRagSettingsModal}
				ragSettings={knowledge.meta?.rag_settings ?? {}}
				on:save={async (e) => {
					const newRagSettings = e.detail;
					// Update knowledge meta with new RAG settings
					knowledge.meta = {
						...(knowledge.meta ?? {}),
						rag_settings: Object.keys(newRagSettings).length > 0 ? newRagSettings : undefined
					};
					// Trigger save
					const res = await updateKnowledgeById(localStorage.token, id, {
						name: knowledge.name,
						description: knowledge.description,
						meta: knowledge.meta,
						access_grants: knowledge.access_grants ?? []
					}).catch((err) => {
						toast.error(`${err}`);
						return null;
					});
					if (res) {
						toast.success($i18n.t('RAG settings updated'));
						_knowledge.set(await getKnowledgeBases(localStorage.token));
					}
				}}
			/>
		{/if}
		<div class="w-full px-2">
			<div class=" flex w-full">
				<div class="flex-1">
					<div class="flex items-center justify-between w-full">
						<div class="w-full flex justify-between items-center">
							<input
								type="text"
								class="text-left w-full text-lg bg-transparent outline-hidden flex-1"
								bind:value={knowledge.name}
								aria-label={$i18n.t('Knowledge Name')}
								placeholder={$i18n.t('Knowledge Name')}
								disabled={!knowledge?.write_access}
								on:input={() => {
									changeDebounceHandler();
								}}
							/>

							<div class="shrink-0 mr-2.5">
								{#if fileItemsTotal}
									<div class="text-xs text-gray-500">
										<!-- {$i18n.t('{{COUNT}} files')} -->
										{$i18n.t('{{COUNT}} files', {
											COUNT: fileItemsTotal
										})}
									</div>
								{/if}
							</div>
						</div>

						{#if knowledge?.write_access}
							<div class="self-center shrink-0 flex gap-1">
								{#if !isExternalKnowledge}
									<button
										class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center"
										type="button"
										on:click={() => {
											showRagSettingsModal = true;
										}}
										title={$i18n.t('RAG Settings')}
									>
										<AdjustmentsHorizontal strokeWidth="2.5" className="size-3.5" />

										<div class="text-sm font-medium shrink-0">
											{$i18n.t('RAG')}
										</div>
									</button>
								{/if}
								<button
									class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center"
									type="button"
									on:click={() => {
										showAccessControlModal = true;
									}}
								>
									<LockClosed strokeWidth="2.5" className="size-3.5" />

									<div class="text-sm font-medium shrink-0">
										{$i18n.t('Access')}
									</div>
								</button>
								{#if !isExternalKnowledge}
									<button
										class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center disabled:opacity-50 disabled:cursor-not-allowed"
										type="button"
										disabled={isReindexing}
										on:click={() => {
											showReindexConfirmModal = true;
										}}
										title={$i18n.t('Re-index all files in this knowledge base')}
									>
										{#if isReindexing}
											<Spinner className="size-3.5" />
										{:else}
											<ArrowPath strokeWidth="2.5" className="size-3.5" />
										{/if}

										<div class="text-sm font-medium shrink-0">
											{$i18n.t('Reindex')}
										</div>
									</button>
								{/if}
							</div>
						{:else}
							<div class="text-xs shrink-0 text-gray-500">
								{$i18n.t('Read Only')}
							</div>
						{/if}
					</div>

					<div class="flex w-full items-center">
						<input
							type="text"
							class="text-left text-xs w-full text-gray-500 bg-transparent outline-hidden flex-1"
							bind:value={knowledge.description}
							aria-label={$i18n.t('Knowledge Description')}
							placeholder={$i18n.t('Knowledge Description')}
							disabled={!knowledge?.write_access}
							on:input={() => {
								changeDebounceHandler();
							}}
						/>

						<div class="hidden md:block">
							<Tooltip content={$i18n.t('Click to copy ID')}>
								<button
									class="text-xs text-gray-500 font-mono shrink-0 px-2 py-1 rounded-lg cursor-pointer hover:underline transition whitespace-nowrap"
									on:click={() => {
										copyToClipboard(id);
										toast.success($i18n.t('ID copied to clipboard'));
									}}
								>
									{id}
								</button>
							</Tooltip>
						</div>
					</div>
				</div>
			</div>
		</div>

		{#if !isExternalKnowledge && knowledge?.meta?.sharepoint_source}
			<div class="mt-1 mb-1 px-1 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 32 32"
					class="size-3.5 flex-shrink-0"
					fill="none"
				>
					<mask
						id="sp-icon"
						style="mask-type:alpha"
						maskUnits="userSpaceOnUse"
						x="0"
						y="6"
						width="32"
						height="20"
					>
						<path
							d="M7.82979 26C3.50549 26 0 22.5675 0 18.3333C0 14.1921 3.35322 10.8179 7.54613 10.6716C9.27535 7.87166 12.4144 6 16 6C20.6308 6 24.5169 9.12183 25.5829 13.3335C29.1316 13.3603 32 16.1855 32 19.6667C32 23.0527 29 26 25.8723 25.9914L7.82979 26Z"
							fill="#C4C4C4"
						/>
					</mask>
					<g mask="url(#sp-icon)">
						<path
							d="M7.83 26C5.38 26 3.19 24.9 1.75 23.17L18.04 16.33L30.71 23.46C29.59 24.92 27.91 26 26 25.99H7.83Z"
							fill="#0364B8"
						/>
						<path
							d="M25.58 13.31L18.04 16.33L30.71 23.46C31.52 22.41 32 21.09 32 19.67C32 16.19 29.13 13.36 25.58 13.33Z"
							fill="#0078D4"
						/>
						<path
							d="M7.06 10.7L18.04 16.33L25.58 13.31C24.51 9.11 20.62 6 16 6C12.41 6 9.28 7.87 7.55 10.67L7.06 10.7Z"
							fill="#1490DF"
						/>
						<path
							d="M1.75 23.17L18.04 16.33L7.06 10.7C3.1 11.08 0 14.35 0 18.33C0 20.17.66 21.85 1.75 23.17Z"
							fill="#28A8EA"
						/>
					</g>
				</svg>
				<span class="truncate">
					{$i18n.t('SharePoint: {{folder}}', {
						folder: knowledge.meta.sharepoint_source.folder_name
					})}
				</span>
				{#if knowledge?.write_access}
					<button
						class="ml-auto flex-shrink-0 px-2 py-0.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-xs flex items-center gap-1"
						disabled={sharePointImporting}
						on:click={sharePointReimportHandler}
					>
						{#if sharePointImporting}
							<Spinner className="size-3" />
						{:else}
							<ArrowPath className="size-3" />
						{/if}
						{$i18n.t('Re-import')}
					</button>
				{/if}
			</div>
		{/if}

		<div
			class="mt-2 mb-2.5 py-2 -mx-0 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30 flex-1"
		>
			{#if isExternalKnowledge}
				<div class="p-5 flex flex-col gap-4">
					<div class="flex flex-wrap gap-2 text-xs">
						<div class="px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850">
							{$i18n.t('Connected')}
						</div>
						<div class="px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850">
							{$i18n.t('Read Only')}
						</div>
						<div class="px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850">
							{knowledge?.meta?.external?.provider ?? $i18n.t('Provider')}
						</div>
						<div class="px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850">
							{$i18n.t('Service Account')}
						</div>
					</div>

					<div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
						<div>
							<div class="text-xs text-gray-500 mb-1">{$i18n.t('Mapped Source')}</div>
							<div class="rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2">
								{knowledge?.meta?.external?.source?.name ?? $i18n.t('Not configured')}
							</div>
						</div>
						<div>
							<div class="text-xs text-gray-500 mb-1">{$i18n.t('Auth Mode')}</div>
							<div class="rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2">
								{$i18n.t('Admin-managed service account')}
							</div>
						</div>
					</div>

					<div class="text-xs text-gray-500">
						{$i18n.t(
							'This knowledge base retrieves from a connected source. Open WebUI can query it, but cannot upload, sync, edit, delete, reset, or reindex its source data.'
						)}
					</div>

					<div class="flex flex-col gap-2">
						<div class="font-medium text-sm">{$i18n.t('Test Query')}</div>
						<div class="flex gap-2">
							<input
								class="w-full text-sm rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 outline-hidden"
								bind:value={externalTestQuery}
								placeholder={$i18n.t('Ask this knowledge source a test question')}
							/>
							<button
								class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black text-sm"
								on:click={externalTestHandler}
							>
								{$i18n.t('Test')}
							</button>
						</div>
					</div>

					{#if externalTestResult}
						<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3 text-xs">
							<div class="font-medium mb-2">{$i18n.t('Preview')}</div>
							{#each externalTestResult.documents ?? [] as document, idx}
								<div class="border-t border-gray-100 dark:border-gray-800 py-2">
									<div class="line-clamp-4">{document}</div>
									<div class="text-gray-500 mt-1">
										{externalTestResult.metadatas?.[idx]?.source ?? ''}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				<div class="px-3.5 flex flex-1 items-center w-full space-x-2 py-0.5 pb-2">
					<div class="flex flex-1 items-center">
						<div class=" self-center ml-1 mr-3">
							<Search className="size-3.5" />
						</div>
						<input
							class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
							bind:value={query}
							on:input={handleSearchInput}
							aria-label={$i18n.t('Search Collection')}
							placeholder={$i18n.t('Search Collection')}
							on:focus={() => {
								selectedFileId = null;
								selectedFile = null;
								selectedFileContent = '';
								loadingFileContent = false;
							}}
						/>

						<Dropdown align="end">
							<button
								class="p-1.5 mr-1 rounded-xl text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
								type="button"
							>
								<AdjustmentsHorizontal className="size-3.5" strokeWidth="2" />
							</button>

							<div slot="content">
								<div
									class="min-w-[180px] rounded-2xl px-1 py-1 border border-gray-100 dark:border-gray-800 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
								>
									<button
										class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl w-full"
										type="button"
										on:click={() => {
											includeContent = !includeContent;
										}}
									>
										<Checkbox
											state={includeContent ? 'checked' : 'unchecked'}
											on:change={(e) => {
												includeContent = e.detail === 'checked';
											}}
										/>
										{$i18n.t('File content')}
									</button>
								</div>
							</div>
						</Dropdown>

						{#if knowledge?.write_access}
							<div>
								<AddContentMenu
									showSharePointImport={!isExternalKnowledge &&
										$config?.features?.enable_sharepoint_import}
									onUpload={(data) => {
										if (data.type === 'directory') {
											uploadDirectoryHandler();
										} else if (data.type === 'new_directory') {
											showNewDirectoryModal = true;
										} else if (data.type === 'web') {
											showAddWebpageModal = true;
										} else if (data.type === 'text') {
											showAddTextContentModal = true;
										} else if (data.type === 'sharepoint') {
											showSharePointPicker = true;
										} else {
											document.getElementById('files-input').click();
										}
									}}
									onSync={async () => {
										pendingSyncFiles = await collectDirectoryFiles();
										if (pendingSyncFiles?.length) {
											showSyncConfirmModal = true;
										}
									}}
									onReset={() => {
										showResetConfirm = true;
									}}
								/>
							</div>
						{/if}
					</div>
				</div>

				<div class="px-3 flex justify-between">
					<div
						class="flex w-full bg-transparent overflow-x-auto scrollbar-none"
						on:wheel={(e) => {
							if (e.deltaY !== 0) {
								e.preventDefault();
								e.currentTarget.scrollLeft += e.deltaY;
							}
						}}
					>
						<div
							class="flex gap-3 w-fit text-center text-sm rounded-full bg-transparent px-0.5 whitespace-nowrap"
						>
							<DropdownOptions
								align="start"
								className="flex shrink-0 items-center gap-2 px-3 py-1.5 text-sm bg-gray-50 dark:bg-gray-850 rounded-xl placeholder-gray-400 outline-hidden focus:outline-hidden"
								bind:value={viewOption}
								items={[
									{ value: null, label: $i18n.t('All') },
									{ value: 'created', label: $i18n.t('Created by you') },
									{ value: 'shared', label: $i18n.t('Shared with you') }
								]}
								onChange={(value) => {
									if (value) {
										localStorage.workspaceViewOption = value;
									} else {
										delete localStorage.workspaceViewOption;
									}
								}}
							/>

							<DropdownOptions
								align="start"
								bind:value={sortKey}
								placeholder={$i18n.t('Sort')}
								items={[
									{ value: 'name', label: $i18n.t('Name') },
									{ value: 'created_at', label: $i18n.t('Created At') },
									{ value: 'updated_at', label: $i18n.t('Updated At') }
								]}
							/>

							{#if sortKey}
								<DropdownOptions
									align="start"
									bind:value={direction}
									items={[
										{ value: 'asc', label: $i18n.t('Asc') },
										{ value: null, label: $i18n.t('Desc') }
									]}
								/>
							{/if}
						</div>
					</div>
				</div>

				{#if currentDirectoryId !== null}
					<div class="px-5 mt-2">
						<KnowledgeBreadcrumbs
							rootLabel={knowledge.name}
							{breadcrumbs}
							onNavigate={(dirId) => navigateToDirectory(dirId)}
							onMoveFile={(fileId, dirId) => moveFileToDirectoryHandler(fileId, dirId)}
							onMoveDir={(dirId, targetId) => moveDirectoryHandler(dirId, targetId)}
						/>
					</div>
				{/if}

				{#if syncing}
					<div class="mx-2.5 mt-2.5 -mb-0.5">
						<div class="flex items-center gap-2.5 rounded-xl py-2 px-3 bg-gray-50 dark:bg-gray-850">
							<Spinner className="size-3.5 shrink-0" />
							<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
								{syncing}
							</div>
						</div>
					</div>
				{/if}

				{#if fileItems !== null && fileItemsTotal !== null}
					<div class="flex flex-row flex-1 gap-3 px-2.5 mt-2">
						<div class="flex-1 flex">
							<div class=" flex flex-col w-full space-x-2 rounded-lg h-full">
								<div class="w-full h-full flex flex-col min-h-full">
									{#if fileItems.length > 0 || directoryItems.length > 0}
										<div class=" flex overflow-y-auto h-full w-full scrollbar-hidden text-xs">
											<Files
												files={fileItems}
												directories={directoryItems}
												{knowledge}
												{selectedFileId}
												onClick={(fileId) => {
													// Row click → quick read-only preview modal (fork WIP).
													if (fileItems) {
														const file = fileItems.find((f) => f.id === fileId);
														if (file) {
															selectedFile = file;
															showFilePreview = true;
														}
													}
												}}
												onEdit={(fileId) => {
													// Pencil → open the editable content drawer (old onClick path).
													selectedFileId = fileId;

													if (fileItems) {
														const file = fileItems.find((file) => file.id === selectedFileId);
														if (file) {
															fileSelectHandler(file);
														} else {
															selectedFileId = null;
															selectedFile = null;
															selectedFileContent = '';
															loadingFileContent = false;
														}
													}
												}}
												onDelete={(fileId) => {
													selectedFileId = null;
													selectedFile = null;
													selectedFileContent = '';
													loadingFileContent = false;

													deleteFileHandler(fileId);
												}}
												onRename={(fileId, name) => renameFileHandler(fileId, name)}
												onNavigateDirectory={(dirId) => navigateToDirectory(dirId)}
												onRenameDirectory={(id, name) => renameDirectoryHandler(id, name)}
												onDeleteDirectory={(id) => confirmDeleteDirectory(id)}
												onMoveFileToDirectory={(fileId, dirId) =>
													moveFileToDirectoryHandler(fileId, dirId)}
												onMoveDirectoryToDirectory={(dirId, targetId) =>
													moveDirectoryHandler(dirId, targetId)}
											/>
										</div>

										{#if fileItemsTotal > 30}
											<Pagination bind:page={currentPage} count={fileItemsTotal} perPage={30} />
										{/if}
									{:else}
										<div
											class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs"
										>
											<div>
												{$i18n.t('No content found')}
											</div>
										</div>
									{/if}
								</div>
							</div>
						</div>

						{#if selectedFile !== null}
							<FileItemModal bind:show={showFilePreview} item={selectedFile} edit={false} />
						{/if}

						{#if selectedFileId !== null}
							<Drawer
								className="h-full"
								show={selectedFileId !== null}
								onClose={() => {
									selectedFileId = null;
									selectedFile = null;
									selectedFileContent = '';
									loadingFileContent = false;
								}}
							>
								<div class="flex flex-col justify-start h-full max-h-full">
									<div class=" flex flex-col w-full h-full max-h-full">
										<div class="shrink-0 flex items-center p-2">
											<div class="mr-2">
												<button
													class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
													aria-label={$i18n.t('Close')}
													on:click={() => {
														selectedFileId = null;
														selectedFile = null;
														selectedFileContent = '';
														loadingFileContent = false;
													}}
												>
													<ChevronLeft strokeWidth="2.5" />
												</button>
											</div>
											<div class=" flex-1 text-lg line-clamp-1">
												{selectedFile?.meta?.name}
											</div>

											{#if knowledge?.write_access}
												<div>
													<button
														class="flex self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
														disabled={isSaving || loadingFileContent}
														on:click={() => {
															updateFileContentHandler();
														}}
													>
														{$i18n.t('Save')}
														{#if isSaving}
															<div class="ml-2 self-center">
																<Spinner />
															</div>
														{/if}
													</button>
												</div>
											{/if}
										</div>

										{#key selectedFile?.id}
											<textarea
												class="w-full h-full text-sm outline-none resize-none px-3 py-2"
												bind:value={selectedFileContent}
												disabled={!knowledge?.write_access || loadingFileContent}
												aria-label={$i18n.t('File content')}
												placeholder={$i18n.t('Add content here')}
											></textarea>
										{/key}
									</div>
								</div>
							</Drawer>
						{/if}
					</div>
				{:else}
					<div class="my-10">
						<Spinner className="size-4" />
					</div>
				{/if}
			{/if}
		</div>
	{:else}
		<Spinner className="size-5" />
	{/if}
</div>

<ConfirmDialog
	bind:show={showDeleteDirectoryConfirm}
	title={$i18n.t('Delete directory?')}
	on:confirm={() => {
		deleteDirectoryHandler(!deleteDirectoryContents);
	}}
	on:cancel={() => {
		pendingDeleteDirectoryId = null;
	}}
>
	<div class="text-sm text-gray-700 dark:text-gray-300 flex-1 line-clamp-3 mb-2">
		{$i18n.t(`Are you sure you want to delete this directory?`)}
	</div>

	<div class="flex items-center gap-1.5">
		<input type="checkbox" bind:checked={deleteDirectoryContents} />

		<div class="text-xs text-gray-500">
			{$i18n.t('Delete all contents inside this directory')}
		</div>
	</div>
</ConfirmDialog>

<ConfirmDialog
	bind:show={showResetConfirm}
	title={$i18n.t('Reset knowledge base?')}
	on:confirm={async () => {
		await resetKnowledgeById(localStorage.token, id);
		toast.success($i18n.t('Knowledge base has been reset'));
		init();
	}}
>
	<div class="text-sm text-gray-700 dark:text-gray-300 flex-1 line-clamp-3">
		{$i18n.t(
			'This will remove all files and directories from this knowledge base. This action cannot be undone.'
		)}
	</div>
</ConfirmDialog>
