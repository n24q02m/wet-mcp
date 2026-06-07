import asyncio
import time
from unittest.mock import patch

import pytest

from wet_mcp.embedder import CloudEmbeddingBackend


@pytest.mark.asyncio
async def test_embed_texts_parallel():
    backend = CloudEmbeddingBackend("text-embedding-3-small")
    # Small batch size to trigger multiple batches easily
    backend.MAX_BATCH_SIZE = 2

    texts = ["t1", "t2", "t3", "t4"]  # 2 batches
    delay = 0.5

    async def mocked_embed_batch_inner(batch, dimensions=None):
        await asyncio.sleep(delay)
        return [[0.1] * 1536] * len(batch)

    with patch.object(
        backend, "_embed_batch_inner", side_effect=mocked_embed_batch_inner
    ):
        start_time = time.perf_counter()
        results = await backend.embed_texts(texts)
        end_time = time.perf_counter()

    duration = end_time - start_time
    assert len(results) == 4
    # If sequential, duration >= 1.0. If parallel, duration approx 0.5.
    assert duration < delay * 1.5, (
        f"Duration {duration} was not fast enough, expected < {delay * 1.5}"
    )
