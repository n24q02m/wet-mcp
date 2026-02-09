# media Tool Documentation

Media discovery and download from web pages.

## Actions

### list
Scan a page and return media URLs with metadata.

**Parameters:**
- `url` (required): Page URL to scan
- `media_type`: Type of media - images, videos, audio, files, all (default: all)
- `max_items`: Maximum items per type (default: 10)

**Example:**
```json
{"action": "list", "url": "https://example.com/gallery", "media_type": "images"}
```

**Returns:**
```json
{
  "images": [
    {"src": "https://...", "alt": "...", "width": 800, "height": 600}
  ],
  "videos": [],
  "audio": []
}
```

---

### download
Download specific media files to local storage for further analysis or processing.
Use this when you need to inspect the actual file content (e.g., sending an image to a Vision LLM).

**Parameters:**
- `media_urls` (required): List of media URLs to download
- `output_dir`: Output directory (default: ~/.wet-mcp/downloads)

**Example:**
```json
{"action": "download", "media_urls": ["https://example.com/image.jpg"]}
```

**Returns:**
```json
[
  {"url": "...", "path": "/path/to/file.jpg", "size": 12345}
]
```

---

### analyze
Analyze a local media file using configured LLM (requires API_KEYS).
Supports images, videos, audio, and text files.

**Parameters:**
- `url` (required): Local file path to analyze
- `prompt`: Analysis prompt (default: "Describe this image in detail.")

**Example:**
```json
{"action": "analyze", "url": "/path/to/image.jpg", "prompt": "What objects are in this image?"}
```

**Returns:**
LLM analysis text response.

**Requirements:**
- Set `API_KEYS` environment variable (format: `GOOGLE_API_KEY:xxx`)
- Set `LLM_MODELS` to specify model (default: `gemini/gemini-3-flash-preview`)

---

## Workflow

1. Use `list` to discover media on a page
2. Review the results (optionally have AI analyze)
3. Use `download` to save specific files locally
4. Use `analyze` to get LLM insights on downloaded files
