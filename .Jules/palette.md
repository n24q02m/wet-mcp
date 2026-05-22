## 2024-05-22 - Suggest valid parameters in JSON errors for backend MCP tools
**Learning:** In backend MCP tools without traditional UIs, enhancing the developer experience by adding actionable suggestions (e.g., using `difflib.get_close_matches`) to JSON error responses for invalid parameters (like configuration keys) makes the interface much more pleasant and intuitive to use.
**Action:** Always consider adding "Did you mean '...'?" suggestions to error messages when a user inputs an invalid command, key, or option from a known list.
