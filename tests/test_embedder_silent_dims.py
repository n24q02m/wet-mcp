"""Regression tests for the silent semantic-degrade bug.

When a cloud provider rejects the requested output ``dimensions`` (e.g.
``cohere/embed-v4.0`` at wet's default 768; cohere-v4 supports only
{256, 512, 1024, 1536}), litellm wraps the provider's HTTP 422 as an
``APIConnectionError`` whose class name contains "connection" and whose
``status_code`` is a synthetic 500. The old ``_is_retryable`` matched the
"connection" substring, so the dimensions-fallback was bypassed and the call
was retried 3x with the SAME rejected dims, then gave up -> ``_embed`` returned
None -> semantic search silently degraded to keyword search with no error
surfaced.

These tests reproduce that exact shape (litellm exceptions, dims-aware mock)
and lock in the fix: unsupported-dimensions recover via retry-without-dims +
local truncate, and permanent client errors are never retried.
"""

from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import APIConnectionError, RateLimitError

from wet_mcp.embedder import MAX_RETRIES, CloudEmbeddingBackend, _is_retryable

# The exact provider body cohere returns for an unsupported output_dimension,
# as litellm surfaces it after wrapping the 422 in APIConnectionError.
_COHERE_422_BODY = (
    'CohereException - {"message": "768 is not a valid output_dimension, '
    'use one of 256, 512, 1024, 1536"}'
)


def _wrapped_422() -> APIConnectionError:
    """A litellm APIConnectionError wrapping cohere's 422 dims rejection."""
    return APIConnectionError(
        message=_COHERE_422_BODY, llm_provider="cohere", model="embed-v4.0"
    )


class TestIsRetryableClassification:
    """`_is_retryable` must classify on error semantics, not class name."""

    def test_wrapped_422_unsupported_dimension_is_not_retryable(self):
        exc = _wrapped_422()
        # Guard: this really is the tricky shape (class name -> "connection",
        # synthetic 500) that fooled the old substring matcher.
        assert "connection" in str(exc).lower()
        assert getattr(exc, "status_code", None) == 500

        assert _is_retryable(exc) is False

    def test_genuine_connection_error_is_retryable(self):
        exc = APIConnectionError(
            message="Connection error.", llm_provider="cohere", model="embed-v4.0"
        )
        assert _is_retryable(exc) is True

    def test_rate_limit_is_retryable(self):
        exc = RateLimitError(
            message="rate limit exceeded", llm_provider="cohere", model="embed-v4.0"
        )
        assert _is_retryable(exc) is True

    def test_invalid_api_key_is_not_retryable(self):
        exc = APIConnectionError(
            message="AuthenticationError - invalid api key",
            llm_provider="cohere",
            model="embed-v4.0",
        )
        assert _is_retryable(exc) is False


class TestWrappedDimsRejectionRecovery:
    """The litellm-wrapped 422 must trigger the retry-without-dims fallback."""

    async def test_wrapped_422_triggers_dims_fallback_and_truncates(self):
        # Dims-aware fake: the provider REJECTS every dims-bearing call (as
        # cohere-v4 does at 768) and only succeeds when dims are dropped.
        # A non-dims-aware mock would let the buggy retry "recover" by luck and
        # hide the defect.
        native_dim = 1536

        async def fake_call(texts, dimensions=None):
            if dimensions is not None:
                raise _wrapped_422()
            return [[0.1] * native_dim for _ in texts]

        backend = CloudEmbeddingBackend(model="cohere/embed-v4.0")
        with patch.object(
            backend, "_call_provider", new=AsyncMock(side_effect=fake_call)
        ) as mock_call:
            result = await backend._embed_batch_inner(["hello"], dimensions=768)

        # Recovered: valid vector truncated locally to the requested 768.
        assert len(result[0]) == 768
        assert result[0] == [0.1] * 768
        # Exactly two provider calls: dims=768 (rejected) then dims=None (ok).
        assert mock_call.call_count == 2
        assert mock_call.call_args_list[0].args[1] == 768
        assert mock_call.call_args_list[1].args[1] is None

    async def test_wrapped_422_is_not_retried_with_same_dims(self):
        # If the fallback did NOT fire, the buggy code would retry MAX_RETRIES
        # times with the same rejected dims. Assert it does NOT.
        async def always_reject(texts, dimensions=None):
            raise _wrapped_422()

        backend = CloudEmbeddingBackend(model="cohere/embed-v4.0")
        with patch.object(
            backend, "_call_provider", new=AsyncMock(side_effect=always_reject)
        ) as mock_call:
            with pytest.raises(APIConnectionError):
                await backend._embed_batch_inner(["hello"], dimensions=768)

        # 1 dims=768 attempt (rejected) + 1 dims=None fallback attempt (also
        # rejected) = 2. NOT MAX_RETRIES retries of the same bad dims.
        assert mock_call.call_count == 2
        assert mock_call.call_count < MAX_RETRIES + 1
        assert mock_call.call_args_list[0].args[1] == 768
        assert mock_call.call_args_list[1].args[1] is None
