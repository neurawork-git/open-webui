<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import DropdownMenu from '$lib/components/common/DropdownMenu.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowUpCircle from '$lib/components/icons/ArrowUpCircle.svelte';
	import BarsArrowUp from '$lib/components/icons/BarsArrowUp.svelte';
	import FolderOpen from '$lib/components/icons/FolderOpen.svelte';
	import NewFolderAlt from '$lib/components/icons/NewFolderAlt.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowUturnLeft from '$lib/components/icons/ArrowUturnLeft.svelte';

	const i18n = getContext('i18n');

	export let onClose: Function = () => {};

	export let onSync: Function = () => {};
	export let onUpload: Function = (data) => {};
	export let onReset: Function = () => {};
	export let showSharePointImport: boolean = false;

	let show = false;
</script>

<Dropdown
	bind:show
	onOpenChange={(state) => {
		if (state === false) {
			onClose();
		}
	}}
	align="end"
>
	<Tooltip content={$i18n.t('Add Content')}>
		<button
			class="p-1.5 rounded-xl bg-transparent transition text-xs flex items-center space-x-1 hover:text-gray-900 dark:hover:text-gray-100"
			aria-label={$i18n.t('Add Content')}
			on:click={(e) => {
				e.stopPropagation();
				show = true;
			}}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 16 16"
				fill="currentColor"
				class="w-4 h-4"
			>
				<path
					d="M8.75 3.75a.75.75 0 0 0-1.5 0v3.5h-3.5a.75.75 0 0 0 0 1.5h3.5v3.5a.75.75 0 0 0 1.5 0v-3.5h3.5a.75.75 0 0 0 0-1.5h-3.5v-3.5Z"
				/>
			</svg>
		</button>
	</Tooltip>

	<div slot="content">
		<DropdownMenu className="min-w-[200px] transition">
			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onUpload({ type: 'new_directory' });
					show = false;
				}}
			>
				<NewFolderAlt />
				<div class="flex items-center">{$i18n.t('New directory')}</div>
			</button>

			<hr class="my-1 border-gray-100 dark:border-gray-800" />

			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onUpload({ type: 'files' });
				}}
			>
				<ArrowUpCircle strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Upload files')}</div>
			</button>

			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onUpload({ type: 'directory' });
				}}
			>
				<FolderOpen strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Upload directory')}</div>
			</button>

			<Tooltip
				content={$i18n.t(
					'Sync a local directory with this knowledge base. Only new and modified files will be uploaded. The directory structure will be mirrored.'
				)}
				className="w-full"
			>
				<button
					class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
					on:click={() => {
						onSync();
					}}
				>
					<ArrowPath strokeWidth="2" />
					<div class="flex items-center">{$i18n.t('Sync directory')}</div>
				</button>
			</Tooltip>

			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onUpload({ type: 'web' });
				}}
			>
				<GlobeAlt strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Add webpage')}</div>
			</button>

			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onUpload({ type: 'text' });
				}}
			>
				<BarsArrowUp strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Add text content')}</div>
			</button>

			{#if showSharePointImport}
				<button
					class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl w-full"
					on:click={() => {
						onUpload({ type: 'sharepoint' });
					}}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="size-4" fill="none">
						<mask
							id="mask0_87_7796"
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
						<g mask="url(#mask0_87_7796)">
							<path
								d="M7.83017 26.0001C5.37824 26.0001 3.18957 24.8966 1.75391 23.1691L18.0429 16.3335L30.7089 23.4647C29.5926 24.9211 27.9066 26.0001 26.0004 25.9915C23.1254 26.0001 12.0629 26.0001 7.83017 26.0001Z"
								fill="#0364B8"
							/>
							<path
								d="M25.5785 13.3149L18.043 16.3334L30.709 23.4647C31.5199 22.4065 32.0004 21.0916 32.0004 19.6669C32.0004 16.1857 29.1321 13.3605 25.5833 13.3337C25.5817 13.3274 25.5801 13.3212 25.5785 13.3149Z"
								fill="#0078D4"
							/>
							<path
								d="M7.06445 10.7028L18.0423 16.3333L25.5779 13.3148C24.5051 9.11261 20.6237 6 15.9997 6C12.4141 6 9.27508 7.87166 7.54586 10.6716C7.3841 10.6773 7.22358 10.6877 7.06445 10.7028Z"
								fill="#1490DF"
							/>
							<path
								d="M1.7535 23.1687L18.0425 16.3331L7.06471 10.7026C3.09947 11.0792 0 14.3517 0 18.3331C0 20.1665 0.657197 21.8495 1.7535 23.1687Z"
								fill="#28A8EA"
							/>
						</g>
					</svg>
					<div class="flex items-center">{$i18n.t('Import from SharePoint')}</div>
				</button>
			{/if}

			<hr class="my-1 border-gray-100 dark:border-gray-800" />

			<button
				class="select-none flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-xs hover:text-gray-900 dark:hover:text-gray-100"
				on:click={() => {
					onReset();
					show = false;
				}}
			>
				<ArrowUturnLeft strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Reset')}</div>
			</button>
		</DropdownMenu>
	</div>
</Dropdown>
