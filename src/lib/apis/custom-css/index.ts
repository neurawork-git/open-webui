import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getCustomCss = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/custom-css`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateCustomCss = async (token: string, css: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/custom-css`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ css: css })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Re-fetch the stylesheet app.html links, so a save takes effect without a reload.
 * The backend sends `Cache-Control: no-cache`, but the query bust also defeats any
 * proxy in front of it.
 */
export const reloadCustomCss = () => {
	const link = document.querySelector<HTMLLinkElement>(
		'link[rel="stylesheet"][href*="custom.css"]'
	);

	if (link) {
		link.href = `/static/custom.css?v=${Date.now()}`;
	}
};
