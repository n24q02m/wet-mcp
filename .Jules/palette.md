## 2025-05-16 - Outdated Help Documentation

**Learning**: The `help` tool's description contains outdated information regarding the `media` tool's capabilities. It incorrectly states that `media` can "analyze images/videos/audio", even though the `media.analyze` action was removed in v2.0.0. This causes confusion for users relying on the `help` documentation.
**Action**: Always verify that summary documentation (like the "Quick guide" in tool docstrings) stays perfectly synchronized with breaking API changes (like feature removals) to prevent sending users down dead-end interaction paths.
