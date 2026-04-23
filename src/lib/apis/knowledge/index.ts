import { WEBUI_API_BASE_URL } from '$lib/constants';

export const createNewKnowledge = async (
	token: string,
	name: string,
	description: string,
	accessGrants: object[]
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: name,
			description: description,
			access_grants: accessGrants
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getKnowledgeBases = async (token: string = '', page: number | null = null) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (page) searchParams.append('page', page.toString());

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const searchKnowledgeBases = async (
	token: string = '',
	query: string | null = null,
	viewOption: string | null = null,
	page: number | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (query) searchParams.append('query', query);
	if (viewOption) searchParams.append('view_option', viewOption);
	if (page) searchParams.append('page', page.toString());

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/search?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const searchKnowledgeFiles = async (
	token: string,
	query?: string | null = null,
	viewOption?: string | null = null,
	orderBy?: string | null = null,
	direction?: string | null = null,
	page: number = 1
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (query) searchParams.append('query', query);
	if (viewOption) searchParams.append('view_option', viewOption);
	if (orderBy) searchParams.append('order_by', orderBy);
	if (direction) searchParams.append('direction', direction);
	searchParams.append('page', page.toString());

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/search/files?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const searchKnowledgeFilesById = async (
	token: string,
	id: string,
	query?: string | null = null,
	viewOption?: string | null = null,
	orderBy?: string | null = null,
	direction?: string | null = null,
	page: number = 1
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (query) searchParams.append('query', query);
	if (viewOption) searchParams.append('view_option', viewOption);
	if (orderBy) searchParams.append('order_by', orderBy);
	if (direction) searchParams.append('direction', direction);
	searchParams.append('page', page.toString());

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/${id}/files?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type RagSettings = {
	top_k?: number | null;
	top_k_reranker?: number | null;
	relevance_threshold?: number | null;
	enable_hybrid_search?: boolean | null;
	enable_reranking?: boolean | null;
	hybrid_bm25_weight?: number | null;
	full_context?: boolean | null;
};

type KnowledgeMeta = {
	rag_settings?: RagSettings;
};

type KnowledgeUpdateForm = {
	name?: string;
	description?: string;
	data?: object;
	meta?: KnowledgeMeta | null;
	access_grants?: object[];
};

export const updateKnowledgeById = async (token: string, id: string, form: KnowledgeUpdateForm) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: form?.name ? form.name : undefined,
			description: form?.description ? form.description : undefined,
			data: form?.data ? form.data : undefined,
			meta: form?.meta !== undefined ? form.meta : undefined,
			access_grants: form.access_grants
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateKnowledgeAccessGrants = async (
	token: string,
	id: string,
	accessGrants: any[]
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/access/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ access_grants: accessGrants })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const addFileToKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/add`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const removeFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const resetKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/reset`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const reindexKnowledgeFiles = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/reindex`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const importSharePointFolder = async (
	token: string,
	id: string,
	driveId: string,
	itemId: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/sharepoint/import`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			drive_id: driveId,
			item_id: itemId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const importSharePointSite = async (token: string, id: string, siteId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/sharepoint/import-site`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ site_id: siteId })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export type SharePointSiteSearchResult = {
	id: string;
	name: string;
	display_name: string;
	web_url: string;
};

export type SharePointSitesPage = {
	sites: SharePointSiteSearchResult[];
	next_link: string | null;
};

export type SharePointDriveSummary = {
	id: string;
	name: string;
	drive_type: string;
	root_item_id: string;
	total_size: number;
};

export type SharePointSiteDrives = {
	site_name: string;
	site_url: string;
	drives: SharePointDriveSummary[];
};

export type SharePointChildItem = {
	id: string;
	name: string;
	is_folder: boolean;
	size: number;
	child_count: number;
	content_type?: string | null;
};

export type SharePointChildren = {
	parent_name: string;
	parent_size: number;
	folders: SharePointChildItem[];
	files: SharePointChildItem[];
	next_link: string | null;
};

const throwing = (res: any) => {
	if (res === null) throw new Error('Request failed');
	return res;
};

export const listSharePointSites = async (
	token: string,
	query: string = '*',
	nextLink: string | null = null
): Promise<SharePointSitesPage> => {
	const params = new URLSearchParams();
	if (query) params.set('query', query);
	if (nextLink) params.set('next_link', nextLink);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/sharepoint/sites?${params.toString()}`,
		{
			method: 'GET',
			headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
		}
	).then(async (r) => {
		if (!r.ok) throw await r.json();
		return r.json();
	});
	return throwing(res);
};

export const listSharePointSiteDrives = async (
	token: string,
	siteId: string
): Promise<SharePointSiteDrives> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/sharepoint/sites/${encodeURIComponent(siteId)}/drives`,
		{
			method: 'GET',
			headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
		}
	).then(async (r) => {
		if (!r.ok) throw await r.json();
		return r.json();
	});
	return throwing(res);
};

export const listSharePointFolderChildren = async (
	token: string,
	driveId: string,
	itemId: string,
	nextLink: string | null = null
): Promise<SharePointChildren> => {
	const params = new URLSearchParams();
	if (nextLink) params.set('next_link', nextLink);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/sharepoint/drives/${encodeURIComponent(driveId)}/items/${encodeURIComponent(itemId)}/children?${params.toString()}`,
		{
			method: 'GET',
			headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
		}
	).then(async (r) => {
		if (!r.ok) throw await r.json();
		return r.json();
	});
	return throwing(res);
};

export const searchSharePointSites = async (
	token: string,
	query: string
): Promise<SharePointSiteSearchResult[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/sharepoint/sites/search?query=${encodeURIComponent(query)}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

export const reimportSharePointFolder = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/sharepoint/reimport`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const reindexKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/reindex`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const exportKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/export`, {
		method: 'GET',
		headers: {
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.blob();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
