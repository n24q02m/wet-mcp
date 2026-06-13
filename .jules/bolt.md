## 2025-05-14 - [Coverage Enhancement: setup.py Error Paths]
**Learning:** The project uses a pattern of dedicated `_coverage.py` test files to handle edge cases and error paths that are difficult to reach in standard comprehensive tests. Mocking `importlib.util.find_spec` with side effects (like `Exception`) is effective for covering `try...except` blocks around module discovery.
**Action:** Always check for existing `_coverage.py` files when tasked with increasing coverage, and follow the established pattern for mocking internal library functions.
