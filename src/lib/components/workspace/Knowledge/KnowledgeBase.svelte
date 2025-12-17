<script lang="ts">
	import Fuse from 'fuse.js';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { onMount, getContext, onDestroy, tick } from 'svelte';
	const i18n = getContext('i18n');

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
		getFileById
	} from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		getKnowledgeById,
		importSharePointFolder,
		reimportSharePointFolder,
		reindexKnowledgeById,
		removeFileFromKnowledgeById,
		resetKnowledgeById,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		updateKnowledgeAccessGrants,
		searchKnowledgeFilesById
	} from '$lib/apis/knowledge';
	import { processWeb, processYoutubeVideo } from '$lib/apis/retrieval';

	import { blobToFile, isYoutubeUrl } from '$lib/utils';
	import { openOneDrivePicker } from '$lib/utils/onedrive-file-picker';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';

	import SyncConfirmDialog from '../../common/ConfirmDialog.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import RagSettingsModal from '$lib/components/common/RagSettingsModal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import FilesOverlay from '$lib/components/chat/MessageInput/FilesOverlay.svelte';
	import DropdownOptions from '$lib/components/common/DropdownOptions.svelte';
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

	let showSyncConfirmModal = false;
	let showAccessControlModal = false;
	let sharePointImporting = false;

	let minSize = 0;
	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids: string[];
		};
		meta?: {
			rag_settings?: RagSettings;
		} | null;
		files: any[];
		access_grants?: any[];
		write_access?: boolean;
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let knowledgeId = null;

	let selectedFileId = null;
	let selectedFile = null;
	let selectedFileContent = '';

	let showReindexConfirmModal = false;
	let isReindexing = false;
	let showRagSettingsModal = false;

	let inputFiles = null;

	let query = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let viewOption = null;
	let sortKey = null;
	let direction = null;

	let currentPage = 1;
	let fileItems = null;
	let fileItemsTotal = null;

	const reset = () => {
		currentPage = 1;
	};

	const init = async () => {
		reset();
		await getItemsPage();
	};

	// Debounce only query changes
	$: if (query !== undefined) {
		clearTimeout(searchDebounceTimer);

		searchDebounceTimer = setTimeout(() => {
			getItemsPage();
		}, 300);
	}

	// Immediate response to filter/pagination changes
	$: if (
		knowledgeId !== null &&
		viewOption !== undefined &&
		sortKey !== undefined &&
		direction !== undefined &&
		currentPage !== undefined
	) {
		getItemsPage();
	}

	$: if (
		query !== undefined &&
		viewOption !== undefined &&
		sortKey !== undefined &&
		direction !== undefined
	) {
		reset();
	}

	const getItemsPage = async () => {
		if (knowledgeId === null) return;

		fileItems = null;
		fileItemsTotal = null;

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
			currentPage
		).catch(() => {
			return null;
		});

		if (res) {
			fileItems = res.items;
			fileItemsTotal = res.total;
		}
		return res;
	};

	const fileSelectHandler = async (file) => {
		try {
			selectedFile = file;
			selectedFileContent = selectedFile?.data?.content || '';
		} catch (e) {
			toast.error($i18n.t('Failed to load file content.'));
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

					const uploadedFile = await uploadFile(localStorage.token, file).catch((e) => {
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
							await addFileHandler(uploadedFile.id);
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
					await addFileHandler(uploadedFile.id);
				}
			} else {
				toast.error($i18n.t('Failed to upload file.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const sharePointImportHandler = async (driveId: string, itemId: string) => {
		if (!knowledge) return;
		sharePointImporting = true;

		try {
			const result = await importSharePointFolder(
				localStorage.token,
				knowledge.id,
				driveId,
				itemId
			);

			if (result) {
				if (result.imported > 0) {
					toast.success(
						$i18n.t('Imported {{count}} files from "{{folder}}"', {
							count: result.imported,
							folder: result.folder_name
						})
					);
				}
				if (result.failed > 0) {
					toast.warning(
						$i18n.t('{{count}} files failed to import', { count: result.failed })
					);
				}
				if (result.skipped_folders.length > 0) {
					toast.info(
						$i18n.t('Skipped {{count}} subfolders (not supported in v1)', {
							count: result.skipped_folders.length
						})
					);
				}
				if (result.imported === 0 && result.failed === 0) {
					toast.info($i18n.t('Folder is empty — no files to import'));
				}
				await getItemsPage();
			}
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
					toast.warning(
						$i18n.t('{{count}} files failed to import', { count: result.failed })
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

	const uploadDirectoryHandler = async () => {
		// Check if File System Access API is supported
		const isFileSystemAccessSupported = 'showDirectoryPicker' in window;

		try {
			if (isFileSystemAccessSupported) {
				// Modern browsers (Chrome, Edge) implementation
				await handleModernBrowserUpload();
			} else {
				// Firefox fallback
				await handleFirefoxUpload();
			}
		} catch (error) {
			handleUploadError(error);
		}
	};

	// Helper function to check if a path contains hidden folders
	const hasHiddenFolder = (path) => {
		return path.split('/').some((part) => part.startsWith('.'));
	};

	// Modern browsers implementation using File System Access API
	const handleModernBrowserUpload = async () => {
		const dirHandle = await window.showDirectoryPicker();
		let totalFiles = 0;
		let uploadedFiles = 0;

		// Function to update the UI with the progress
		const updateProgress = () => {
			const percentage = (uploadedFiles / totalFiles) * 100;
			toast.info(
				$i18n.t('Upload Progress: {{uploadedFiles}}/{{totalFiles}} ({{percentage}}%)', {
					uploadedFiles: uploadedFiles,
					totalFiles: totalFiles,
					percentage: percentage.toFixed(2)
				})
			);
		};

		// Recursive function to count all files excluding hidden ones
		async function countFiles(dirHandle) {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				if (entry.kind === 'file') {
					totalFiles++;
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await countFiles(entry);
					}
				}
			}
		}

		// Recursive function to process directories excluding hidden files and folders
		async function processDirectory(dirHandle, path = '') {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				const entryPath = path ? `${path}/${entry.name}` : entry.name;

				// Skip if the path contains any hidden folders
				if (hasHiddenFolder(entryPath)) continue;

				if (entry.kind === 'file') {
					const file = await entry.getFile();
					const fileWithPath = new File([file], entryPath, { type: file.type });

					await uploadFileHandler(fileWithPath);
					uploadedFiles++;
					updateProgress();
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await processDirectory(entry, entryPath);
					}
				}
			}
		}

		await countFiles(dirHandle);
		updateProgress();

		if (totalFiles > 0) {
			await processDirectory(dirHandle);
		} else {
			console.log('No files to upload.');
		}
	};

	// Firefox fallback implementation using traditional file input
	const handleFirefoxUpload = async () => {
		return new Promise((resolve, reject) => {
			// Create hidden file input
			const input = document.createElement('input');
			input.type = 'file';
			input.webkitdirectory = true;
			input.directory = true;
			input.multiple = true;
			input.style.display = 'none';

			// Add input to DOM temporarily
			document.body.appendChild(input);

			input.onchange = async () => {
				try {
					const files = Array.from(input.files)
						// Filter out files from hidden folders
						.filter((file) => !hasHiddenFolder(file.webkitRelativePath));

					let totalFiles = files.length;
					let uploadedFiles = 0;

					// Function to update the UI with the progress
					const updateProgress = () => {
						const percentage = (uploadedFiles / totalFiles) * 100;
						toast.info(
							$i18n.t('Upload Progress: {{uploadedFiles}}/{{totalFiles}} ({{percentage}}%)', {
								uploadedFiles: uploadedFiles,
								totalFiles: totalFiles,
								percentage: percentage.toFixed(2)
							})
						);
					};

					updateProgress();

					// Process all files
					for (const file of files) {
						// Skip hidden files (additional check)
						if (!file.name.startsWith('.')) {
							const relativePath = file.webkitRelativePath || file.name;
							const fileWithPath = new File([file], relativePath, { type: file.type });

							await uploadFileHandler(fileWithPath);
							uploadedFiles++;
							updateProgress();
						}
					}

					// Clean up
					document.body.removeChild(input);
					resolve();
				} catch (error) {
					reject(error);
				}
			};

			input.onerror = (error) => {
				document.body.removeChild(input);
				reject(error);
			};

			// Trigger file picker
			input.click();
		});
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

	// Helper function to maintain file paths within zip
	const syncDirectoryHandler = async () => {
		if (fileItems.length > 0) {
			const res = await resetKnowledgeById(localStorage.token, id).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				fileItems = [];
				toast.success($i18n.t('Knowledge reset successfully.'));

				// Upload directory
				uploadDirectoryHandler();
			}
		} else {
			uploadDirectoryHandler();
		}
	};

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
		const res = await addFileToKnowledgeById(localStorage.token, id, fileId).catch((e) => {
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

	let debounceTimeout = null;
	let mediaQuery;

	let dragged = false;
	let isSaving = false;

	const updateFileContentHandler = async () => {
		if (isSaving) {
			console.log('Save operation already in progress, skipping...');
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

		const handleUploadingFileFolder = (items) => {
			for (const item of items) {
				if (item.isFile) {
					item.file((file) => {
						uploadFileHandler(file);
					});
					continue;
				}

				// Not sure why you have to call webkitGetAsEntry and isDirectory seperate, but it won't work if you try item.webkitGetAsEntry().isDirectory
				const wkentry = item.webkitGetAsEntry();
				const isDirectory = wkentry.isDirectory;
				if (isDirectory) {
					// Read the directory
					wkentry.createReader().readEntries(
						(entries) => {
							handleUploadingFileFolder(entries);
						},
						(error) => {
							console.error('Error reading directory entries:', error);
						}
					);
				} else {
					toast.info($i18n.t('Uploading file...'));
					uploadFileHandler(item.getAsFile());
					toast.success($i18n.t('File uploaded!'));
				}
			}
		};

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const inputItems = e.dataTransfer?.items;

				if (inputItems && inputItems.length > 0) {
					handleUploadingFileFolder(inputItems);
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
<SyncConfirmDialog
	bind:show={showSyncConfirmModal}
	message={$i18n.t(
		'This will reset the knowledge base and sync all files. Do you wish to continue?'
	)}
	on:confirm={() => {
		syncDirectoryHandler();
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
					access_grants: knowledge.access_grants
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
							</div>
						{:else}
							<div class="text-xs shrink-0 text-gray-500">
								{$i18n.t('Read Only')}
							</div>
						{/if}
					</div>

					<div class="flex w-full">
						<input
							type="text"
							class="text-left text-xs w-full text-gray-500 bg-transparent outline-hidden"
							bind:value={knowledge.description}
							aria-label={$i18n.t('Knowledge Description')}
							placeholder={$i18n.t('Knowledge Description')}
							disabled={!knowledge?.write_access}
							on:input={() => {
								changeDebounceHandler();
							}}
						/>
					</div>
				</div>
			</div>
		</div>

		{#if knowledge?.meta?.sharepoint_source}
			<div class="mt-1 mb-1 px-1 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="size-3.5 flex-shrink-0" fill="none">
					<mask id="sp-icon" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="0" y="6" width="32" height="20">
						<path d="M7.82979 26C3.50549 26 0 22.5675 0 18.3333C0 14.1921 3.35322 10.8179 7.54613 10.6716C9.27535 7.87166 12.4144 6 16 6C20.6308 6 24.5169 9.12183 25.5829 13.3335C29.1316 13.3603 32 16.1855 32 19.6667C32 23.0527 29 26 25.8723 25.9914L7.82979 26Z" fill="#C4C4C4"/>
					</mask>
					<g mask="url(#sp-icon)">
						<path d="M7.83 26C5.38 26 3.19 24.9 1.75 23.17L18.04 16.33L30.71 23.46C29.59 24.92 27.91 26 26 25.99H7.83Z" fill="#0364B8"/>
						<path d="M25.58 13.31L18.04 16.33L30.71 23.46C31.52 22.41 32 21.09 32 19.67C32 16.19 29.13 13.36 25.58 13.33Z" fill="#0078D4"/>
						<path d="M7.06 10.7L18.04 16.33L25.58 13.31C24.51 9.11 20.62 6 16 6C12.41 6 9.28 7.87 7.55 10.67L7.06 10.7Z" fill="#1490DF"/>
						<path d="M1.75 23.17L18.04 16.33L7.06 10.7C3.1 11.08 0 14.35 0 18.33C0 20.17.66 21.85 1.75 23.17Z" fill="#28A8EA"/>
					</g>
				</svg>
				<span class="truncate">
					{$i18n.t('SharePoint: {{folder}}', { folder: knowledge.meta.sharepoint_source.folder_name })}
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
			<div class="px-3.5 flex flex-1 items-center w-full space-x-2 py-0.5 pb-2">
				<div class="flex flex-1 items-center">
					<div class=" self-center ml-1 mr-3">
						<Search className="size-3.5" />
					</div>
					<input
						class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={query}
						aria-label={$i18n.t('Search Collection')}
						placeholder={$i18n.t('Search Collection')}
						on:focus={() => {
							selectedFileId = null;
						}}
					/>

					{#if knowledge?.write_access}
						<div>
							<AddContentMenu
								showSharePointImport={$config?.features?.enable_onedrive_integration && $config?.features?.enable_onedrive_business}
								onUpload={(data) => {
									if (data.type === 'directory') {
										uploadDirectoryHandler();
									} else if (data.type === 'web') {
										showAddWebpageModal = true;
									} else if (data.type === 'text') {
										showAddTextContentModal = true;
									} else if (data.type === 'sharepoint') {
										(async () => {
											try {
												const result = await openOneDrivePicker('organizations', 'folders');
												if (result?.items?.length > 0) {
													const folder = result.items[0];
													await sharePointImportHandler(
														folder.parentReference.driveId,
														folder.id
													);
												}
											} catch (e) {
												toast.error(`SharePoint: ${e}`);
											}
										})();
									} else {
										document.getElementById('files-input').click();
									}
								}}
								onSync={() => {
									showSyncConfirmModal = true;
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

			{#if fileItems !== null && fileItemsTotal !== null}
				<div class="flex flex-row flex-1 gap-3 px-2.5 mt-2">
					<div class="flex-1 flex">
						<div class=" flex flex-col w-full space-x-2 rounded-lg h-full">
							<div class="w-full h-full flex flex-col min-h-full">
								{#if fileItems.length > 0}
									<div class=" flex overflow-y-auto h-full w-full scrollbar-hidden text-xs">
										<Files
											files={fileItems}
											{knowledge}
											{selectedFileId}
											onClick={(fileId) => {
												selectedFileId = fileId;

												if (fileItems) {
													const file = fileItems.find((file) => file.id === selectedFileId);
													if (file) {
														fileSelectHandler(file);
													} else {
														selectedFile = null;
													}
												}
											}}
											onDelete={(fileId) => {
												selectedFileId = null;
												selectedFile = null;

												deleteFileHandler(fileId);
											}}
										/>
									</div>

									{#if fileItemsTotal > 30}
										<Pagination bind:page={currentPage} count={fileItemsTotal} perPage={30} />
									{/if}
								{:else}
									<div class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs">
										<div>
											{$i18n.t('No content found')}
										</div>
									</div>
								{/if}
							</div>
						</div>
					</div>

					{#if selectedFileId !== null}
						<Drawer
							className="h-full"
							show={selectedFileId !== null}
							onClose={() => {
								selectedFileId = null;
								selectedFile = null;
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
													disabled={isSaving}
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

									{#key selectedFile.id}
										<textarea
											class="w-full h-full text-sm outline-none resize-none px-3 py-2"
											bind:value={selectedFileContent}
											disabled={!knowledge?.write_access}
											aria-label={$i18n.t('File content')}
											placeholder={$i18n.t('Add content here')}
										/>
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
		</div>
	{:else}
		<Spinner className="size-5" />
	{/if}
</div>
