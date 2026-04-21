import type { PopupRequest, PublicClientApplication } from '@azure/msal-browser';
import { v4 as uuidv4 } from 'uuid';

class OneDriveConfig {
	private static instance: OneDriveConfig;
	private clientIdPersonal: string = '';
	private clientIdBusiness: string = '';
	private sharepointUrl: string = '';
	private sharepointTenantId: string = '';
	private msalInstance: PublicClientApplication | null = null;
	private currentAuthorityType: 'personal' | 'organizations' = 'personal';

	private constructor() {}

	public static getInstance(): OneDriveConfig {
		if (!OneDriveConfig.instance) {
			OneDriveConfig.instance = new OneDriveConfig();
		}
		return OneDriveConfig.instance;
	}

	public async initialize(authorityType?: 'personal' | 'organizations'): Promise<void> {
		if (authorityType && this.currentAuthorityType !== authorityType) {
			this.currentAuthorityType = authorityType;
			this.msalInstance = null;
		}
		await this.getCredentials();
	}

	public async ensureInitialized(authorityType?: 'personal' | 'organizations'): Promise<void> {
		await this.initialize(authorityType);
	}

	private async getCredentials(): Promise<void> {
		const response = await fetch('/api/config', {
			headers: {
				'Content-Type': 'application/json'
			},
			credentials: 'include'
		});

		if (!response.ok) {
			throw new Error('Failed to fetch OneDrive credentials');
		}

		const config = await response.json();

		this.clientIdPersonal = config.onedrive?.client_id_personal;
		this.clientIdBusiness = config.onedrive?.client_id_business;
		this.sharepointUrl = config.onedrive?.sharepoint_url;
		this.sharepointTenantId = config.onedrive?.sharepoint_tenant_id;

		if (!this.clientIdPersonal && !this.clientIdBusiness) {
			throw new Error('OneDrive personal or business client ID not configured');
		}
	}

	public async getMsalInstance(
		authorityType?: 'personal' | 'organizations'
	): Promise<PublicClientApplication> {
		await this.ensureInitialized(authorityType);

		if (!this.msalInstance) {
			const authorityEndpoint =
				this.currentAuthorityType === 'organizations'
					? this.sharepointTenantId || 'common'
					: 'consumers';

			const clientId =
				this.currentAuthorityType === 'organizations'
					? this.clientIdBusiness
					: this.clientIdPersonal;

			if (!clientId) {
				throw new Error('OneDrive client ID not configured');
			}

			const msalParams = {
				auth: {
					authority: `https://login.microsoftonline.com/${authorityEndpoint}`,
					clientId: clientId,
					redirectUri: window.location.origin
				}
			};

			const { PublicClientApplication } = await import('@azure/msal-browser');
			this.msalInstance = new PublicClientApplication(msalParams);
			if (this.msalInstance.initialize) {
				await this.msalInstance.initialize();
			}
		}

		return this.msalInstance;
	}

	public getAuthorityType(): 'personal' | 'organizations' {
		return this.currentAuthorityType;
	}

	public getSharepointUrl(): string {
		return this.sharepointUrl;
	}

	public getSharepointTenantId(): string {
		return this.sharepointTenantId;
	}

	public getBaseUrl(): string {
		if (this.currentAuthorityType === 'organizations') {
			if (!this.sharepointUrl || this.sharepointUrl === '') {
				throw new Error('Sharepoint URL not configured');
			}

			let sharePointBaseUrl = this.sharepointUrl.replace(/^https?:\/\//, '');
			sharePointBaseUrl = sharePointBaseUrl.replace(/\/$/, '');

			return `https://${sharePointBaseUrl}`;
		} else {
			return 'https://onedrive.live.com/picker';
		}
	}
}

// Retrieve OneDrive access token
async function getToken(
	resource?: string,
	authorityType?: 'personal' | 'organizations'
): Promise<string> {
	const config = OneDriveConfig.getInstance();
	await config.ensureInitialized(authorityType);

	const currentAuthorityType = config.getAuthorityType();

	const scopes =
		currentAuthorityType === 'organizations'
			? [`${resource || config.getBaseUrl()}/.default`]
			: ['OneDrive.ReadWrite'];

	const authParams: PopupRequest = { scopes };
	let accessToken = '';

	try {
		const msalInstance = await config.getMsalInstance(authorityType);
		const resp = await msalInstance.acquireTokenSilent(authParams);
		accessToken = resp.accessToken;
	} catch {
		const msalInstance = await config.getMsalInstance(authorityType);
		try {
			const resp = await msalInstance.loginPopup(authParams);
			msalInstance.setActiveAccount(resp.account);
			if (resp.idToken) {
				const resp2 = await msalInstance.acquireTokenSilent(authParams);
				accessToken = resp2.accessToken;
			}
		} catch (popupError) {
			throw new Error(
				'Failed to login: ' +
					(popupError instanceof Error ? popupError.message : String(popupError))
			);
		}
	}

	if (!accessToken) {
		throw new Error('Failed to acquire access token');
	}

	return accessToken;
}

// Acquires a Microsoft Graph-scoped token (separate from the SharePoint picker token).
// Required for direct Graph API calls: folder listing, download URL retrieval.
async function getGraphToken(
	authorityType?: 'personal' | 'organizations'
): Promise<string> {
	const config = OneDriveConfig.getInstance();
	await config.ensureInitialized(authorityType);

	const scopes = ['https://graph.microsoft.com/.default'];
	const authParams: PopupRequest = { scopes };
	let accessToken = '';

	try {
		const msalInstance = await config.getMsalInstance(authorityType);
		const resp = await msalInstance.acquireTokenSilent(authParams);
		accessToken = resp.accessToken;
	} catch {
		const msalInstance = await config.getMsalInstance(authorityType);
		try {
			const resp = await msalInstance.loginPopup(authParams);
			msalInstance.setActiveAccount(resp.account);
			if (resp.idToken) {
				const resp2 = await msalInstance.acquireTokenSilent(authParams);
				accessToken = resp2.accessToken;
			}
		} catch (popupError) {
			throw new Error(
				'Failed to acquire Graph token: ' +
					(popupError instanceof Error ? popupError.message : String(popupError))
			);
		}
	}

	if (!accessToken) {
		throw new Error('Failed to acquire Graph access token');
	}

	return accessToken;
}

// Verifies that the Azure App Registration has Files.Read.All and the Graph token works.
export async function verifyGraphAccess(
	authorityType?: 'personal' | 'organizations'
): Promise<{ success: boolean; message: string }> {
	try {
		const token = await getGraphToken(authorityType);
		const resp = await fetch(
			'https://graph.microsoft.com/v1.0/me/drive/root/children?$top=1&$select=id,name',
			{ headers: { Authorization: `Bearer ${token}` } }
		);

		if (resp.status === 200) {
			return { success: true, message: 'Graph API access verified' };
		}
		if (resp.status === 403) {
			return {
				success: false,
				message:
					'Graph API access denied (403) — Files.Read.All missing from App Registration or not consented'
			};
		}
		if (resp.status === 401) {
			return {
				success: false,
				message:
					'Graph API unauthorized (401) — token acquisition failed or App Registration mismatch'
			};
		}
		return { success: false, message: `Graph API returned unexpected status: ${resp.status}` };
	} catch (err) {
		return {
			success: false,
			message: `Graph API verification failed: ${err instanceof Error ? err.message : String(err)}`
		};
	}
}

interface PickerParams {
	sdk: string;
	entry: {
		oneDrive: Record<string, unknown>;
	};
	authentication: Record<string, unknown>;
	messaging: {
		origin: string;
		channelId: string;
	};
	search: {
		enabled: boolean;
	};
	typesAndSources: {
		mode: string;
		pivots: Record<string, boolean>;
	};
}

interface PickerResult {
	command?: string;
	items?: OneDriveFileInfo[];
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	[key: string]: any;
}

// Get picker parameters based on account type
function getPickerParams(mode: 'files' | 'folders' = 'files'): PickerParams {
	const channelId = uuidv4();
	const config = OneDriveConfig.getInstance();

	const params: PickerParams = {
		sdk: '8.0',
		entry: {
			oneDrive: {}
		},
		authentication: {},
		messaging: {
			origin: window?.location?.origin || '',
			channelId
		},
		search: {
			enabled: true
		},
		typesAndSources: {
			mode,
			pivots: {
				oneDrive: true,
				recent: true,
				myOrganization: config.getAuthorityType() === 'organizations'
			}
		}
	};

	// For personal accounts, set files object in oneDrive
	if (config.getAuthorityType() !== 'organizations') {
		params.entry.oneDrive = { files: {} };
	}

	return params;
}

interface OneDriveFileInfo {
	id: string;
	name: string;
	parentReference: {
		driveId: string;
	};
	'@sharePoint.endpoint': string;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	[key: string]: any;
}

// Download file from OneDrive
async function downloadOneDriveFile(
	fileInfo: OneDriveFileInfo,
	authorityType?: 'personal' | 'organizations'
): Promise<Blob> {
	const accessToken = await getToken(undefined, authorityType);
	if (!accessToken) {
		throw new Error('Unable to retrieve OneDrive access token.');
	}

	// The endpoint URL is provided in the file info
	const fileInfoUrl = `${fileInfo['@sharePoint.endpoint']}/drives/${fileInfo.parentReference.driveId}/items/${fileInfo.id}`;

	const response = await fetch(fileInfoUrl, {
		headers: {
			Authorization: `Bearer ${accessToken}`
		}
	});

	if (!response.ok) {
		throw new Error(`Failed to fetch file information: ${response.status} ${response.statusText}`);
	}

	const fileData = await response.json();
	const downloadUrl = fileData['@content.downloadUrl'];

	if (!downloadUrl) {
		throw new Error('Download URL not found in file data');
	}

	const downloadResponse = await fetch(downloadUrl);

	if (!downloadResponse.ok) {
		throw new Error(
			`Failed to download file: ${downloadResponse.status} ${downloadResponse.statusText}`
		);
	}

	return await downloadResponse.blob();
}

// Open OneDrive file picker and return selected file metadata
export async function openOneDrivePicker(
	authorityType?: 'personal' | 'organizations',
	mode: 'files' | 'folders' = 'files'
): Promise<PickerResult | null> {
	if (typeof window === 'undefined') {
		throw new Error('Not in browser environment');
	}

	// Initialize OneDrive config with the specified authority type
	const config = OneDriveConfig.getInstance();
	await config.initialize(authorityType);

	return new Promise((resolve, reject) => {
		let pickerWindow: Window | null = null;
		let channelPort: MessagePort | null = null;
		const params = getPickerParams(mode);
		const baseUrl = config.getBaseUrl();

		const handleWindowMessage = (event: MessageEvent) => {
			if (event.source !== pickerWindow) return;
			const message = event.data;
			if (message?.type === 'initialize' && message?.channelId === params.messaging.channelId) {
				channelPort = event.ports?.[0];
				if (!channelPort) return;
				channelPort.addEventListener('message', handlePortMessage);
				channelPort.start();
				channelPort.postMessage({ type: 'activate' });
			}
		};

		const handlePortMessage = async (portEvent: MessageEvent) => {
			const portData = portEvent.data;
			switch (portData.type) {
				case 'notification':
					break;
				case 'command': {
					channelPort?.postMessage({ type: 'acknowledge', id: portData.id });
					const command = portData.data;
					switch (command.command) {
						case 'authenticate': {
							try {
								// Pass the resource from the command for org accounts
								const resource =
									config.getAuthorityType() === 'organizations' ? command.resource : undefined;
								const newToken = await getToken(resource, authorityType);
								if (newToken) {
									channelPort?.postMessage({
										type: 'result',
										id: portData.id,
										data: { result: 'token', token: newToken }
									});
								} else {
									throw new Error('Could not retrieve auth token');
								}
							} catch {
								channelPort?.postMessage({
									type: 'result',
									id: portData.id,
									data: {
										result: 'error',
										error: { code: 'tokenError', message: 'Failed to get token' }
									}
								});
							}
							break;
						}
						case 'close': {
							cleanup();
							resolve(null);
							break;
						}
						case 'pick': {
							channelPort?.postMessage({
								type: 'result',
								id: portData.id,
								data: { result: 'success' }
							});
							cleanup();
							resolve(command);
							break;
						}
						default: {
							channelPort?.postMessage({
								result: 'error',
								error: { code: 'unsupportedCommand', message: command.command },
								isExpected: true
							});
							break;
						}
					}
					break;
				}
			}
		};

		function cleanup() {
			window.removeEventListener('message', handleWindowMessage);
			if (channelPort) {
				channelPort.removeEventListener('message', handlePortMessage);
			}
			if (pickerWindow) {
				pickerWindow.close();
				pickerWindow = null;
			}
		}

		const initializePicker = async () => {
			try {
				const authToken = await getToken(undefined, authorityType);
				if (!authToken) {
					return reject(new Error('Failed to acquire access token'));
				}

				pickerWindow = window.open('', 'OneDrivePicker', 'width=800,height=600');
				if (!pickerWindow) {
					return reject(new Error('Failed to open OneDrive picker window'));
				}

				const queryString = new URLSearchParams({
					filePicker: JSON.stringify(params)
				});

				let url = '';
				if (config.getAuthorityType() === 'organizations') {
					url = baseUrl + `/_layouts/15/FilePicker.aspx?${queryString}`;
				} else {
					url = baseUrl + `?${queryString}`;
				}

				const form = pickerWindow.document.createElement('form');
				form.setAttribute('action', url);
				form.setAttribute('method', 'POST');
				const input = pickerWindow.document.createElement('input');
				input.setAttribute('type', 'hidden');
				input.setAttribute('name', 'access_token');
				input.setAttribute('value', authToken);
				form.appendChild(input);

				pickerWindow.document.body.appendChild(form);
				form.submit();

				window.addEventListener('message', handleWindowMessage);
			} catch (err) {
				if (pickerWindow) {
					pickerWindow.close();
				}
				reject(err);
			}
		};

		initializePicker();
	});
}

// Pick and download file from OneDrive (single file, kept for backward compat)
export async function pickAndDownloadFile(
	authorityType?: 'personal' | 'organizations'
): Promise<{ blob: Blob; name: string } | null> {
	const files = await pickAndDownloadFiles(authorityType);
	return files.length > 0 ? files[0] : null;
}

// Pick and download multiple files from OneDrive
export async function pickAndDownloadFiles(
	authorityType?: 'personal' | 'organizations'
): Promise<{ blob: Blob; name: string }[]> {
	const pickerResult = await openOneDrivePicker(authorityType);

	if (!pickerResult || !pickerResult.items || pickerResult.items.length === 0) {
		return [];
	}

	const results: { blob: Blob; name: string }[] = [];
	for (const item of pickerResult.items) {
		try {
			const blob = await downloadOneDriveFile(item, authorityType);
			results.push({ blob, name: item.name });
		} catch (err) {
			console.error(`Failed to download ${item.name}:`, err);
		}
	}

	return results;
}

export { downloadOneDriveFile, getGraphToken };
