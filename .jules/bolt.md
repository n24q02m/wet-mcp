## 2026-02-21 - Mocking Async Stream Context Managers
**Learning:** `httpx.AsyncClient.stream` is a synchronous method that returns an asynchronous context manager, not a coroutine. When mocking it, verify if the library method is `async def` or just returns an object with `__aenter__`. Using `AsyncMock` for `stream` incorrectly makes it a coroutine, causing `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`.
**Action:** Use `MagicMock` for `stream`, and set its return value to an `AsyncMock` (which acts as the context manager).
