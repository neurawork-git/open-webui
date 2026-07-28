# Live Custom CSS

> Fork-local feature. Lets an Open WebUI instance be re-branded **at runtime** — no image
> rebuild, no redeploy, and above all no design fork per customer.

## Why it exists

Upstream `src/app.html` has always linked a stylesheet:

```html
<link rel="stylesheet" href="/static/custom.css" crossorigin="use-credentials" />
```

…but it is backed by a file in `STATIC_DIR`, and `config.py` deletes every loose file there
on **every backend import**, repopulating from the frontend build (see `FORK_CHANGES.md` §11.1).
So the only durable way to style an instance was to bake CSS into the image — one branch, one
image and one release cadence per customer.

This fork serves that same URL from the `config` table instead. Branding becomes a config
write: one API call, effective immediately, identical across replicas.

## How it works

| Piece        | Where                                                                 |
| ------------ | --------------------------------------------------------------------- |
| Storage      | `config` table, key `ui.custom_css` (default `''`)                    |
| Router       | `backend/open_webui/routers/custom_css.py`                            |
| Registration | `main.py`, **without a prefix and above `app.mount('/static', ...)`** |
| Editor       | Admin → Settings → **Interface** → _Appearance_                       |

The router owns `/static/custom.css` and therefore shadows the (empty) file of the same name.
FastAPI matches routes in registration order, so **the `include_router` call must stay above the
static mount** — otherwise the mount wins, the empty file is served, and all branding vanishes
without a single error in the logs. `test/custom_css/test_custom_css.py` asserts that ordering.

Because the CSS stays a separate stylesheet rather than being inlined into a `<style>` block,
it needs no HTML escaping and cannot break out of its context.

## API

All three endpoints are on the running instance; the two `/api/v1` ones require an **admin**
token or admin API key.

```bash
BASE=https://chat.example.com
TOKEN=...           # admin JWT or API key

# Read (admin)
curl -s -H "Authorization: Bearer $TOKEN" $BASE/api/v1/custom-css

# Write (admin) — replaces the whole stylesheet
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     --data-binary @theme.json $BASE/api/v1/custom-css      # {"css": "..."}

# Reset
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     --data-binary '{"css":""}' $BASE/api/v1/custom-css

# What every browser actually loads (public — the login page needs it)
curl -s -D- $BASE/static/custom.css
```

Send the body as a **file** (`--data-binary @file`), not inline: Git-Bash mangles inline UTF-8,
which matters as soon as the CSS contains `content: "…"` with umlauts.

Responses on the stylesheet carry `Cache-Control: no-cache` plus an `ETag`, so an edit goes live
on the next page load while unchanged CSS still answers `304`.

Limit: **256 KiB** measured in UTF-8 bytes. Over that, `POST` returns `400` and nothing is written.

## Notes

- **Applies everywhere, including the login page** — it is loaded before authentication.
- The admin editor's Save calls `reloadCustomCss()`, which re-fetches the `<link>`, so the change
  is visible immediately without a reload.
- **A broken stylesheet can make the UI hard to operate.** The recovery path is the API, not the
  UI: `POST {"css":""}` with an admin API key. Worst case, delete the `ui.custom_css` row.
- Per-user or per-group themes are deliberately **not** supported — one stylesheet per instance.
  Anything conditional belongs inside the CSS itself (e.g. `html.dark`).
- Image assets (logos, favicons, splash) are _not_ covered — those still come from the frontend
  build. Use `background-image` with a `data:` URI if a logo has to be swapped without a rebuild.
