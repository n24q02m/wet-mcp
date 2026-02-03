"""SearXNG search integration."""

import json

import httpx
from loguru import logger


async def search(
    searxng_url: str,
    query: str,
    categories: str = "general",
    max_results: int = 10,
) -> str:
    """Search via SearXNG API.

    Args:
        searxng_url: SearXNG instance URL
        query: Search query
        categories: Search category (general, images, videos, files)
        max_results: Maximum number of results

    Returns:
        JSON string with search results
    """
    logger.info(f"Searching SearXNG: {query}")

    params = {
        "q": query,
        "format": "json",
        "categories": categories,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{searxng_url}/search",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])[:max_results]

        # Format results
        formatted = []
        for r in results:
            formatted.append(
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "source": r.get("engine", ""),
                }
            )

        output = {
            "results": formatted,
            "total": len(formatted),
            "query": query,
        }

        logger.info(f"Found {len(formatted)} results for: {query}")
        return json.dumps(output, ensure_ascii=False, indent=2)

    except httpx.HTTPStatusError as e:
        logger.error(f"SearXNG HTTP error: {e}")
        return json.dumps({"error": f"HTTP error: {e.response.status_code}"})
    except httpx.RequestError as e:
        logger.error(f"SearXNG request error: {e}")
        return json.dumps({"error": f"Request error: {e}"})
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        return json.dumps({"error": str(e)})
