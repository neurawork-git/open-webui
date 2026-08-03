<script lang="ts">
	// FORK: self-service UI for the LDAP credential store. Storing is the DEFAULT while the
	// feature is on, so the point of this panel is the way OUT -- until it existed, opting
	// out meant issuing an HTTP call by hand. See docs/LDAP_SHAREPOINT_BACKEND.md.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';

	import {
		deleteCredential,
		getCredentialStatus,
		setCredentialOptIn,
		type CredentialStatus
	} from '$lib/apis/users';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');

	let show = false;
	let status: CredentialStatus | null = null;

	const formatDate = (seconds?: number | null) =>
		seconds ? dayjs(seconds * 1000).format('MMM D, YYYY') : '';

	const load = async () => {
		status = await getCredentialStatus(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
	};

	const optInHandler = async (optedIn: boolean) => {
		const res = await setCredentialOptIn(localStorage.token, optedIn).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			status = res;
			toast.success(
				optedIn
					? $i18n.t('Your credential may be stored again on your next sign-in.')
					: $i18n.t('Credential storage turned off. Any stored password was deleted.')
			);
		} else {
			// The switch is bound to `status`, so reload rather than leave it showing a state
			// the server never accepted.
			await load();
		}
	};

	const deleteHandler = async () => {
		const res = await deleteCredential(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Stored password deleted.'));
			await load();
		}
	};

	onMount(load);
</script>

<div class="flex flex-col text-sm">
	<div class="flex justify-between items-center text-sm">
		<div class="font-medium">{$i18n.t('Stored network password')}</div>
		<button
			class="text-xs font-medium text-gray-500"
			type="button"
			on:click={() => {
				show = !show;
			}}>{show ? $i18n.t('Hide') : $i18n.t('Show')}</button
		>
	</div>

	{#if show}
		<div class="py-2.5 space-y-2.5">
			<div class="text-xs text-gray-500">
				{$i18n.t(
					'Your Active Directory password is kept encrypted so SharePoint imports can run under your own account. It is never shown, here or anywhere else.'
				)}
			</div>

			{#if status}
				<div class="text-xs">
					{#if status.exists}
						<div class="font-medium">{$i18n.t('A password is currently stored.')}</div>
						{#if status.account}
							<div class="text-gray-500">{$i18n.t('Account')}: {status.account}</div>
						{/if}
						{#if status.expires_at}
							<div class="text-gray-500">
								{$i18n.t('Expires')}: {formatDate(status.expires_at)}
							</div>
						{/if}
						{#if status.last_used_at}
							<div class="text-gray-500">
								{$i18n.t('Last used')}: {formatDate(status.last_used_at)}
							</div>
						{/if}
					{:else}
						<div class="text-gray-500">{$i18n.t('No password is stored.')}</div>
					{/if}
				</div>

				<div class="flex justify-between items-center">
					<div class="text-xs font-medium" id="credential-opt-in-label">
						{$i18n.t('Allow storing my password')}
					</div>
					<Switch
						state={status.opted_in}
						ariaLabelledbyId="credential-opt-in-label"
						on:change={(e) => optInHandler(e.detail)}
					/>
				</div>

				{#if status.exists}
					<div class="flex justify-end">
						<button
							class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
							type="button"
							on:click={deleteHandler}
						>
							{$i18n.t('Delete stored password')}
						</button>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>
