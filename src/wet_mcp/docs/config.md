# WET MCP Server - Config Tool

Server configuration and management.

## Actions

### status

Show current server configuration and status.

```json
{"action": "status"}
```

Returns: database stats, embedding model, cache status, SearXNG status, sync settings.

### set

Update a runtime setting.

```json
{"action": "set", "key": "log_level", "value": "DEBUG"}
```

Valid keys:

| Key | Values | Description |
|:----|:-------|:------------|
| `log_level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Server log level |
| `tool_timeout` | Integer (seconds) | Max time per tool call |
| `wet_cache` | `true`, `false` | Enable/disable web cache |
| `sync_enabled` | `true`, `false` | Enable/disable docs sync |
| `sync_remote` | String | Rclone remote name |
| `sync_folder` | String | Remote folder path |
| `sync_interval` | Integer (seconds) | Sync interval |

### cache_clear

Clear web cache (search, extract, crawl, map results).

```json
{"action": "cache_clear"}
```

### docs_reindex

Force re-index documentation for a library.

```json
{"action": "docs_reindex", "key": "fastapi"}
```

### warmup

Pre-download models and run first-time setup (embedding, reranking, SearXNG).

```json
{"action": "warmup"}
```

Returns: status of each component (models downloaded, SearXNG ready, etc.).

### setup_sync

Configure cloud sync for docs index via OAuth Device Code flow.

```json
{"action": "setup_sync"}
```

With explicit remote type:

```json
{"action": "setup_sync", "remote_type": "dropbox"}
```

| Parameter | Required | Default | Description |
|:----------|:---------|:--------|:------------|
| `remote_type` | No | `drive` | Remote type (`drive`, `dropbox`, etc.) |

Returns: authorization instructions and status.

### setup_status

Show current credential state and configured keys.

```json
{"action": "setup_status"}
```

Returns: credential state (`awaiting_setup`, `configured`, `local`), setup URL, detected cloud keys.

### setup_start

Trigger relay setup / show the current setup URL for configuring cloud provider keys via browser. Does not spawn a separate relay session.

```json
{"action": "setup_start"}
```

With `force=true` to reconfigure even when already configured:

```json
{"action": "setup_start", "force": true}
```

| Parameter | Required | Default | Description |
|:----------|:---------|:--------|:------------|
| `force` | No | `false` | Re-trigger setup even if already configured |

Returns `status: "already_configured"` (unless forced), `status: "setup_started"` with `setup_url` in HTTP mode, or `status: "stdio_unsupported"` with env-var guidance in stdio mode.

### setup_skip

Opt into local-only mode (uses local ONNX models, no cloud API keys required).

```json
{"action": "setup_skip"}
```

### setup_reset

Clear all credentials and reset state. Next tool call will prompt setup again.

```json
{"action": "setup_reset"}
```

### setup_complete

Re-resolve credentials from environment after manual configuration.

```json
{"action": "setup_complete"}
```

Returns: updated credential state and whether backends were re-initialized.
