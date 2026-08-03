import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';

// Mock @azure/msal-browser before importing the module under test
const mockAcquireTokenSilent = vi.fn();
const mockLoginPopup = vi.fn();
const mockSetActiveAccount = vi.fn();
const mockInitialize = vi.fn().mockResolvedValue(undefined);

vi.mock('@azure/msal-browser', () => ({
	PublicClientApplication: vi.fn().mockImplementation(() => ({
		acquireTokenSilent: mockAcquireTokenSilent,
		loginPopup: mockLoginPopup,
		setActiveAccount: mockSetActiveAccount,
		initialize: mockInitialize
	}))
}));

// Mock uuid
vi.mock('uuid', () => ({ v4: () => 'test-uuid' }));

// Mock global fetch for both config endpoint and Graph API
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// vitest runs in the `node` environment, so there is no `window`. The two functions under
// test only read `window.location.origin` (for the MSAL redirectUri and the diagnostic
// message), so a stub is enough -- pulling in jsdom for one string would be a heavy way to
// get it. `openOneDrivePicker` guards on `typeof window === 'undefined'`, but no test here
// exercises it.
vi.stubGlobal('window', { location: { origin: 'http://localhost:5173' } });

// Config response that OneDriveConfig.getCredentials() fetches
const configResponse = {
	onedrive: {
		client_id_personal: 'personal-client-id',
		client_id_business: 'business-client-id',
		sharepoint_url: 'https://tenant.sharepoint.com',
		sharepoint_tenant_id: 'tenant-id-123'
	}
};

function mockConfigFetch() {
	mockFetch.mockImplementation((url: string) => {
		if (url === '/api/config') {
			return Promise.resolve({
				ok: true,
				json: () => Promise.resolve(configResponse)
			});
		}
		// Default: return a mock for Graph API calls
		return Promise.resolve({ status: 200, ok: true });
	});
}

describe('onedrive-file-picker: getGraphToken', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		// Reset the OneDriveConfig singleton between tests
		vi.resetModules();
		mockConfigFetch();
	});

	it('acquires a Graph token via silent auth', async () => {
		mockAcquireTokenSilent.mockResolvedValueOnce({ accessToken: 'graph-token-123' });

		const { getGraphToken } = await import('./onedrive-file-picker');
		const token = await getGraphToken('organizations');

		expect(token).toBe('graph-token-123');
		expect(mockAcquireTokenSilent).toHaveBeenCalledWith({
			scopes: ['https://graph.microsoft.com/.default']
		});
	});

	it('falls back to popup when silent auth fails', async () => {
		mockAcquireTokenSilent
			.mockRejectedValueOnce(new Error('no cached token'))
			.mockResolvedValueOnce({ accessToken: 'graph-token-popup' });

		mockLoginPopup.mockResolvedValueOnce({
			account: { username: 'user@test.com' },
			idToken: 'id-token'
		});

		const { getGraphToken } = await import('./onedrive-file-picker');
		const token = await getGraphToken('organizations');

		expect(token).toBe('graph-token-popup');
		expect(mockLoginPopup).toHaveBeenCalledWith({
			scopes: ['https://graph.microsoft.com/.default']
		});
		expect(mockSetActiveAccount).toHaveBeenCalledWith({ username: 'user@test.com' });
	});

	it('throws when both silent and popup fail', async () => {
		mockAcquireTokenSilent.mockRejectedValueOnce(new Error('no cached token'));
		mockLoginPopup.mockRejectedValueOnce(new Error('popup blocked'));

		const { getGraphToken } = await import('./onedrive-file-picker');
		await expect(getGraphToken('organizations')).rejects.toThrow(
			'Failed to acquire Graph token: popup blocked'
		);
	});

	it('throws when popup succeeds but returns no idToken', async () => {
		mockAcquireTokenSilent.mockRejectedValueOnce(new Error('no cached token'));
		mockLoginPopup.mockResolvedValueOnce({
			account: { username: 'user@test.com' },
			idToken: null
		});

		const { getGraphToken } = await import('./onedrive-file-picker');
		await expect(getGraphToken('organizations')).rejects.toThrow(
			'Failed to acquire Graph access token'
		);
	});

	it('uses graph.microsoft.com/.default scope regardless of authority type', async () => {
		mockAcquireTokenSilent.mockResolvedValueOnce({ accessToken: 'token-personal' });

		const { getGraphToken } = await import('./onedrive-file-picker');
		await getGraphToken('personal');

		expect(mockAcquireTokenSilent).toHaveBeenCalledWith({
			scopes: ['https://graph.microsoft.com/.default']
		});
	});
});

describe('onedrive-file-picker: verifyGraphAccess', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.resetModules();
		mockConfigFetch();
		// Default: silent auth succeeds
		mockAcquireTokenSilent.mockResolvedValue({ accessToken: 'graph-token-verify' });
	});

	it('returns success when Graph API returns 200', async () => {
		mockFetch.mockImplementation((url: string) => {
			if (url === '/api/config') {
				return Promise.resolve({ ok: true, json: () => Promise.resolve(configResponse) });
			}
			if (url.includes('graph.microsoft.com')) {
				return Promise.resolve({ status: 200 });
			}
			return Promise.resolve({ status: 500 });
		});

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		const result = await verifyGraphAccess('organizations');

		expect(result).toEqual({ success: true, message: 'Graph API access verified' });
	});

	it('returns failure with diagnostic when Graph API returns 403', async () => {
		mockFetch.mockImplementation((url: string) => {
			if (url === '/api/config') {
				return Promise.resolve({ ok: true, json: () => Promise.resolve(configResponse) });
			}
			if (url.includes('graph.microsoft.com')) {
				return Promise.resolve({ status: 403 });
			}
			return Promise.resolve({ status: 500 });
		});

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		const result = await verifyGraphAccess('organizations');

		expect(result.success).toBe(false);
		expect(result.message).toContain('403');
		expect(result.message).toContain('Files.Read.All');
	});

	it('returns failure with diagnostic when Graph API returns 401', async () => {
		mockFetch.mockImplementation((url: string) => {
			if (url === '/api/config') {
				return Promise.resolve({ ok: true, json: () => Promise.resolve(configResponse) });
			}
			if (url.includes('graph.microsoft.com')) {
				return Promise.resolve({ status: 401 });
			}
			return Promise.resolve({ status: 500 });
		});

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		const result = await verifyGraphAccess('organizations');

		expect(result.success).toBe(false);
		expect(result.message).toContain('401');
	});

	it('returns failure for unexpected status codes', async () => {
		mockFetch.mockImplementation((url: string) => {
			if (url === '/api/config') {
				return Promise.resolve({ ok: true, json: () => Promise.resolve(configResponse) });
			}
			if (url.includes('graph.microsoft.com')) {
				return Promise.resolve({ status: 500 });
			}
			return Promise.resolve({ status: 500 });
		});

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		const result = await verifyGraphAccess('organizations');

		expect(result.success).toBe(false);
		expect(result.message).toContain('500');
	});

	it('catches token acquisition errors and returns failure', async () => {
		mockAcquireTokenSilent.mockRejectedValue(new Error('no cached token'));
		mockLoginPopup.mockRejectedValue(new Error('popup blocked'));

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		const result = await verifyGraphAccess('organizations');

		expect(result.success).toBe(false);
		expect(result.message).toContain('Graph API verification failed');
	});

	it('calls Graph API with correct URL and auth header', async () => {
		mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
			if (url === '/api/config') {
				return Promise.resolve({ ok: true, json: () => Promise.resolve(configResponse) });
			}
			if (url.includes('graph.microsoft.com')) {
				// Verify the auth header
				const headers = opts?.headers as Record<string, string>;
				expect(headers?.Authorization).toBe('Bearer graph-token-verify');
				expect(url).toBe(
					'https://graph.microsoft.com/v1.0/me/drive/root/children?$top=1&$select=id,name'
				);
				return Promise.resolve({ status: 200 });
			}
			return Promise.resolve({ status: 500 });
		});

		const { verifyGraphAccess } = await import('./onedrive-file-picker');
		await verifyGraphAccess('organizations');
	});
});
