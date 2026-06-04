import asyncio
import time
from unittest.mock import patch

import pytest

from wet_mcp.embedder import CloudEmbeddingBackend


@pytest.mark.asyncio
async def test_embed_texts_parallel_execution():
    """Verify that multiple batches are executed in parallel."""
    backend = CloudEmbeddingBackend("text-embedding-3-small")
    # Set a small batch size to trigger multiple batches easily
    backend.MAX_BATCH_SIZE = 2

    texts = ["text1", "text2", "text3", "text4"]
    # 4 texts / 2 per batch = 2 batches

    delay = 0.5

    async def mocked_embed_batch(batch, dimensions=None):
        await asyncio.sleep(delay)
        return [[0.1] for _ in batch]

    with patch.object(
        backend, "_embed_batch_inner", side_effect=mocked_embed_batch
    ) as mock_batch:
        start_time = time.perf_counter()
        results = await backend.embed_texts(texts)
        end_time = time.perf_counter()

        duration = end_time - start_time

        # If sequential, duration would be >= 1.0s (2 * 0.5s)
        # If parallel, duration would be >= 0.5s but < 1.0s
        assert len(results) == 4
        assert mock_batch.call_count == 2
        assert (
            duration < delay * 1.5
        )  # Allow some overhead but should be much less than 2 * delay
        assert duration >= delay
