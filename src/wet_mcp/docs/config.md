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

### Embedding Model

Default local model is `Qwen/Qwen3-Embedding-0.6B` (ONNX). For GGUF with GPU:

```bash
pip install wet-mcp[gguf]
```

Set `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B-GGUF` to use the GGUF backend.

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
