<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getCustomCss, updateCustomCss, reloadCustomCss } from '$lib/apis/custom-css';

	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import AdminSettingField from './AdminSettingField.svelte';

	const i18n: any = getContext('i18n');

	let css = '';
	let loaded = false;

	/**
	 * Called by the parent's save handler. Never throws — a rejected stylesheet
	 * (e.g. over the size limit) must not abort the rest of the Interface save.
	 */
	export const save = async () => {
		if (!loaded) {
			return;
		}

		try {
			await updateCustomCss(localStorage.token, css);
			// The stylesheet is a <link> in app.html, so re-fetching it applies the
			// change to this page immediately instead of waiting for a reload.
			reloadCustomCss();
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	onMount(async () => {
		try {
			const res = await getCustomCss(localStorage.token);
			css = res?.css ?? '';
		} catch (error) {
			toast.error(`${error}`);
		}
		loaded = true;
	});
</script>

<AdminSettingField
	label={$i18n.t('Custom CSS')}
	description={$i18n.t(
		'Applied to every page, including login. Stored in the database and served at /static/custom.css — editable at runtime via GET/POST /api/v1/custom-css. Leave empty for the default theme.'
	)}
>
	<div class="mt-1 h-64 overflow-hidden rounded-lg border border-gray-100 dark:border-gray-850 p-1">
		{#if loaded}
			<CodeEditor
				value={css}
				lang="css"
				className="text-[11px] h-full"
				onChange={(e) => {
					css = e;
				}}
			/>
		{/if}
	</div>
</AdminSettingField>
