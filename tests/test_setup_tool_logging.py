import logging
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger

from wet_mcp.setup_tool import _validate_cloud_models


async def test_validate_cloud_models_logging(caplog):
    """Verify that _validate_cloud_models logs exceptions at DEBUG level."""

    # Loguru doesn't use standard logging by default, so we need to bridge it
    def loguru_caplog_bridge(message):
        logging.getLogger().debug(message.record["message"])

    logger.remove()
    logger.add(loguru_caplog_bridge, level="DEBUG")

    mock_settings = MagicMock()
    mock_settings.embedding_chain.return_value = ["test-embed"]
    mock_settings.rerank_chain.return_value = ["test-rerank"]

    with (
        patch(
            "wet_mcp.embedder.init_backend",
            side_effect=Exception("Embedding initialization failed"),
        ),
        patch(
            "wet_mcp.reranker.init_reranker",
            side_effect=Exception("Reranker initialization failed"),
        ),
        caplog.at_level("DEBUG"),
    ):
        result = await _validate_cloud_models(mock_settings)

    # Cloud ready should be False because embedding failed
    assert result["cloud_ready"] is False

    # Check for embedding failure log
    assert (
        "Cloud embedding candidate test-embed failed: Embedding initialization failed"
        in caplog.text
    )


async def test_validate_cloud_models_reranker_logging(caplog):
    """Verify that _validate_cloud_models logs reranker exceptions at DEBUG level."""

    # Loguru doesn't use standard logging by default, so we need to bridge it
    def loguru_caplog_bridge(message):
        logging.getLogger().debug(message.record["message"])

    logger.remove()
    logger.add(loguru_caplog_bridge, level="DEBUG")

    mock_settings = MagicMock()
    mock_settings.embedding_chain.return_value = ["test-embed"]
    mock_settings.rerank_chain.return_value = ["test-rerank"]

    mock_backend = MagicMock()
    mock_backend.check_available = AsyncMock(return_value=768)

    with (
        patch("wet_mcp.embedder.init_backend", return_value=mock_backend),
        patch(
            "wet_mcp.reranker.init_reranker",
            side_effect=Exception("Reranker initialization failed"),
        ),
        caplog.at_level("DEBUG"),
    ):
        result = await _validate_cloud_models(mock_settings)

    assert result["cloud_ready"] is True
    assert result["embedding"] == {"model": "test-embed", "dims": 768}
    assert result["reranker"] is None

    # Check for reranker failure log
    assert (
        "Cloud reranker test-rerank failed: Reranker initialization failed"
        in caplog.text
    )
