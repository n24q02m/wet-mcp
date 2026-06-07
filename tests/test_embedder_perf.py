import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.embedder import CloudEmbeddingBackend


@pytest.mark.asyncio
async def test_embed_batch_parallel_speedup():
    backend = CloudEmbeddingBackend("text-embedding-3-small")
    backend.MAX_BATCH_SIZE = 10
    n = 30  # 3 batches

    async def mock_call(texts, dimensions=None):
        await asyncio.sleep(0.1)  # Simulate network latency
        return [[float(j)] for j in range(len(texts))]

    with patch.object(
        backend, "_embed_batch_inner", new_callable=AsyncMock, side_effect=mock_call
    ):
        start = time.perf_counter()
        vecs = await backend.embed_texts([f"text_{i}" for i in range(n)])
        end = time.perf_counter()

    assert len(vecs) == n
    # Sequential would take ~0.3s. Parallel should take ~0.1s.
    assert end - start < 0.2, "Batching is not parallelized!"
