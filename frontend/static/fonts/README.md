# Self-hosted fonts

Served at `/app/static/fonts/` by Streamlit's static serving (`enableStaticServing` in `frontend/.streamlit/config.toml`), so visitors' browsers do not contact Google Fonts (#65). The `@font-face` rules are in `frontend/styles.py`.

| Files | Source package | Version | Licence |
|---|---|---|---|
| `source-sans-3-latin-{400,500,600,700}-normal.woff2` | `@fontsource/source-sans-3` (npm) | 5.3.1 | SIL Open Font License 1.1 (`OFL-SourceSans3.txt`) |
| `jetbrains-mono-latin-{400,500}-normal.woff2` | `@fontsource/jetbrains-mono` (npm) | 5.3.0 | SIL Open Font License 1.1 (`OFL-JetBrainsMono.txt`) |

Copied on 26 Nov 2026. Latin subset only: enough for the app's English text; any other character falls back to the system font (Google served further subsets on demand).
