# Dependency and API security notes

Last audited 2026-10-24 with `pip-audit -r requirements.lock` and `pnpm audit --prod`; `gitleaks` reports no secret in any of the repository's commits
(`.gitleaks.toml` allow-lists only the file digests in the results freezes).

## What was fixed in the audit

| Package | From | To | Why |
|---|---|---|---|
| aiohttp, certifi, filelock, pypdf | 3.14.3, 2026.7.22, 4.0.4, 6.19.0 | 3.14.4, 2026.10.19, 4.2.1, 6.21.2 | advisories with patched releases in range |
| opentelemetry-api, -sdk, -semantic-conventions | 1.45.0, 1.45.0, 0.66b0 | 1.45.1, 1.45.1, 0.66b1 | moved together because the three pin each other |
| next (site) | 15.5.26 | 15.5.28 | two advisories, one critical (image optimisation; the site is a static export and does not use it, upgraded anyway) |
| postcss, source-map-js, sharp (site, transitive) | various | overridden to the patched ranges in `web/package.json` | build-time tools; the overrides remove the advisories |
| echarts (site) | 5.x | 6.1.0 | XSS advisory; charts checked by screenshot and the browser check |

## Known and accepted, with the reason

| Package | Advisory count | Why it is not fixed | Exposure |
|---|---|---|---|
| pillow 12.3.0 | 37 (fixed in 13.0.0) | Streamlit 1.61 requires `pillow<13`, so 13 breaks the dashboard | Pillow reads images for the document agent and the corpus generator, all of which are local and read files the project made itself; the public API does not import it |
| chromadb 1.5.9 | 5, no fixed release | none exists | the public API uses it for the assistant's retrieval over a bundled index it built; it accepts no uploaded data |
| oauthlib 3.3.1 | 2 (fixed in a major release, 4.0.0) | pulled in by `requests-oauthlib` through the kubernetes client that chromadb depends on; a major bump was not tested | not used directly; no OAuth flow runs in this project |
| maplibre-gl 4.7.1 (site) | 1 critical (HTML sanitiser bypass, fixed in 6.4.1) | version 6 moved its worker to a separate module that the Next bundler setup here does not load (the map stuck on "loading map"), so the upgrade was tried and reverted | the code never calls `Popup.setHTML` or sets HTML from data (checked by search); the map draws with deck.gl and sets text only, so the sanitiser is not on any path |

Re-run `pip-audit` and `pnpm audit` before each release; the table above is the state on the date above, not a standing guarantee.

## The public API

* Rate limits are per client and per route (`src/api/limits.py`): predictions 30 a minute, questions 5 a minute, reads 120 a minute, and a daily model-call quota that
  is returned if a call is not used; over a limit is `429` with `Retry-After`. A 200-request burst measured 127 `429`s and no `5xx`.
* Inputs are bounded (field ranges, a 4 KB body), CORS admits the site's origin and no one else, and no TMS write route is reachable.
* It holds no secrets in the repository; keys live in the host's environment and `.env` (gitignored), and the site bundle is checked for
  key patterns in CI.
* The free host sleeps when idle and takes up to about a minute to wake; the site shows a waking state and retries.

## Reporting a problem

Open an issue without sensitive detail, or contact the maintainers listed in `CITATION.cff`.
