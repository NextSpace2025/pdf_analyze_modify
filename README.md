# PDF Industrial Analyzer

Desktop tool for PDF OCR analysis and safe filename operations.

## What is implemented

- Industrial-style UI (dark panel-based tool look)
- `context7` MCP attached as the default MCP setting
- External API can be attached separately (optional)
- SQLite persistence with exactly two functional tables:
  - `api_settings`: stores API/MCP configuration
  - `file_rollback_history`: stores filename before/after for rollback
- Rollback feature based on filename before/after diff

## Run

```bash
pip install -r requirements.txt
python app.py
```

## Dev Run (auto restart)

When editing code/config frequently, run:

```bash
python dev_run.py
```

`dev_run.py` watches `src/`, `config/`, `templates/`, and key root files.
On file changes, it automatically restarts `app.py`.

## External API contract (optional)

If `Use External API` is enabled, the app calls:

- `POST {API_BASE_URL}/suggest-name`
- Body:

```json
{
  "reason": "Extracted text successfully.",
  "current_name": "sample.pdf",
  "model": "gpt-4.1-mini",
  "mcp": {
    "name": "context7",
    "url": "https://your-mcp-endpoint"
  }
}
```

- Expected response:

```json
{
  "suggested_name": "OK_sample.pdf"
}
```

If the API call fails, batch rename falls back to local rule-based naming.

## API Base URL separate config

You can set API Base URL outside the app UI:

- Environment variable: `PDF_READER_API_BASE_URL`
- YAML config: `config/api_settings.yaml` -> `api_base_url`

Load order:

1. Value saved in app DB (`api_settings.api_base_url`)
2. `PDF_READER_API_BASE_URL`
3. `config/api_settings.yaml`

## Database

Database file: `config/app_state.db`

Tables:

- `api_settings`
- `file_rollback_history`

`sqlite_sequence` may appear automatically because of SQLite `AUTOINCREMENT`.
