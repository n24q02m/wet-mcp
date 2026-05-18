## 2024-05-18 - Configuration UI Synchronization
**Learning:** Removing deprecated features (like `media.analyze`) from code without updating the corresponding configuration UI (`relay_schema.py`) leaves stale help text that confuses users about available API capabilities.
**Action:** When deprecating or removing features, always audit configuration schemas, help texts, and capability lists (e.g., `capabilityInfo`) to ensure the UI accurately reflects the current feature set. Update associated unit tests that assert these UI labels.
