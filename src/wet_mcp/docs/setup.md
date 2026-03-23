# WET MCP Server - Setup Tool

Server setup and warmup operations.

## Actions

### warmup

Pre-download models and run first-time setup (embedding, reranking, SearXNG).

```json
{"action": "warmup"}
```

Returns: status of each component (models downloaded, SearXNG ready, etc.).

### setup_sync

Configure cloud sync for docs index via rclone.

```json
{"action": "setup_sync"}
```

With explicit remote type:

```json
{"action": "setup_sync", "remote_type": "dropbox"}
```

| Parameter | Required | Default | Description |
|:----------|:---------|:--------|:------------|
| `remote_type` | No | `drive` | Rclone remote type (`drive`, `dropbox`, etc.) |

Returns: rclone authorization instructions and status.
