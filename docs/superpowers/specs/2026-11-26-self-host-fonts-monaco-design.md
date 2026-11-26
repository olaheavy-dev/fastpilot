# Self-host the fonts and the Monaco editor (#65): design

**Date:** 26 Nov 2026. **Size:** a small change (short design). **Issue:** #65.

## Why

Each visit to fastpilot.olaheavy.dev makes the visitor's browser contact two outside services: Google Fonts (for Source Sans 3 and JetBrains Mono) and jsDelivr (for the Playground's Monaco editor). Both receive the visitor's IP address and the page they came from. The privacy note on the site names only Opik. Founder's choice, 25 Nov 2026: "Self-host both (Recommended)".

## Goals

- No request from a visitor's browser goes to `fonts.googleapis.com`, `fonts.gstatic.com` or `cdn.jsdelivr.net`.
- The site looks the same: same fonts and weights, same editor, in both themes.
- A test fails if either outside address comes back.

## Non-goals

- No upgrade of Monaco (stays 0.36.1, the version `streamlit-monaco` 0.1.3 was built for) or of `streamlit-monaco`. The latest Monaco is 0.58.0 (23 Nov 2026) and `streamlit-monaco` has had no release since Sep 2023. Founder's choice, 26 Nov 2026: "Keep 0.36.1, open follow-up (Recommended)"; the follow-up is #69.
- No change to Caddy or the infra repository.
- No change to the privacy note's wording: with this change it stays true as written.

## Anti-goals

- The editor quietly falls back to the plain text box in production because Monaco failed to load. That would pass every unit test and still be a failure. The browser check below must see Monaco itself.
- A build that silently takes a different Monaco file than the one checked.

## How it works today

- `frontend/styles.py:28` has `@import url('https://fonts.googleapis.com/css2?...')`.
- `streamlit-monaco` 0.1.3 ships a built web page. Streamlit serves it to the browser from the installed package folder (`streamlit_monaco/frontend/build/`). One file in it, `_next/static/chunks/583.6eb60e0e19a36bdd.js`, holds the address `https://cdn.jsdelivr.net/npm/monaco-editor@0.36.1/min/vs`, where the editor's loader fetches its files.

## Approaches (for Monaco's files)

| Approach | Trade-off | Picked |
|---|---|---|
| **Download at build, checked** | The Dockerfile downloads the exact npm package, checks its SHA-256, and copies only `min/vs` (11 MB) into the image. The repository stays small; a changed file fails the build. Needs npm's registry at build time. | **Yes.** Founder, 26 Nov 2026: "Download at build, checked (Recommended)". |
| Commit the files to the repository | Builds work offline, but 11 MB stays in git history for good, and an upgrade becomes a large pull request. | No |
| Download, keep only Python syntax | Smaller image, but a later change (another language) breaks quietly. | No |

## Design

### Fonts

1. Add the `.woff2` files for Source Sans 3 (400, 500, 600, 700) and JetBrains Mono (400, 500), Latin subset, to `frontend/static/fonts/`, with each font's `OFL.txt` licence file. Both are under the SIL Open Font License 1.1.
2. Turn on Streamlit's static serving (`[server] enableStaticServing = true` in `frontend/.streamlit/config.toml`). Files in `frontend/static/` are then served at `/app/static/`.
3. Replace the `@import` line with `@font-face` rules that point at `/app/static/fonts/...`, using `font-display: swap` as Google's URL did.
4. **Builder's call:** where the files come from (the official releases or the `@fontsource` packages, both OFL), and whether `[[theme.fontFaces]]` in `config.toml` is a better fit than `@font-face` in `styles.py`. Check the Streamlit docs for the installed version. Either way, keep `font = "sans-serif"` for Streamlit's own widgets unless the change is checked in both themes.

### Monaco

1. In `frontend/Dockerfile`, after `pip install`: download `https://registry.npmjs.org/monaco-editor/-/monaco-editor-0.36.1.tgz`, check SHA-256 `0ffa1c42ef6939339031a1e9c72af6cc863773febe992b85a746dc24a6e07251` (the build fails on a mismatch), and extract only `package/min/vs` into the component's `build/` folder (for example `build/monaco/vs`). Use a separate build stage, so the download tool and the tar file stay out of the final image.
2. A small script (`frontend/scripts/patch_monaco.py`, for example) replaces the jsDelivr address in the built `streamlit-monaco` files with the local path. It fails if it finds no address to replace, or if any `cdn.jsdelivr.net` remains afterwards. That way a new `streamlit-monaco` version can't pass silently.
3. **Builder's call:** the exact local path form. A relative path is resolved against the component's own page (Streamlit serves components under `/component/...`). Check in the browser that the editor's helper scripts (web workers) load from the same site.
4. Keep the Monaco version and SHA-256 in one place in the Dockerfile, with a comment that they must change together with `streamlit-monaco`.

### Tests

- A unit test: no file under `frontend/` (excluding vendored font files) contains `fonts.googleapis.com`, `fonts.gstatic.com` or `cdn.jsdelivr.net`.
- A unit test for the patch script: run it on a copy of the installed `streamlit-monaco` build folder; check the address is replaced and none remains; check that it fails on a folder without the address.
- CI's image-build job: after the build, grep the image's `streamlit_monaco` folder for `cdn.jsdelivr.net` and fail if found.
- Before merge, a browser check of the built image: open Chat and Playground in both themes, and confirm in the network log that no request leaves the site, and that Playground shows Monaco itself (not the "Plain editor" caption).

### Docs

- `docs/production-decisions.md`: record the choice and the founder's words.
- `wiki/`: the frontend page and `wiki/log.md`; `wiki/dependency-updates.md` gets a line: a `streamlit-monaco` update must re-check the patch (the script fails loudly if the address moved).
- `docs/planning/status.md`: #65 moves from next to in review.

## Risks

- **`streamlit-monaco` changes** its bundle in a later version. Mitigated: the patch script fails when the address is missing.
- **npm unavailable at build.** The image build fails; nothing in production changes. Retry later.
- **Font look changes slightly** (a different subset or version). Checked in the browser in both themes.
