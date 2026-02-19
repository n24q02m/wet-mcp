import asyncio
import httpx
import time
from httpx import Response

class MockTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        return Response(200, json={"results": []})

async def measure_inner_loop(n):
    start = time.perf_counter()
    transport = MockTransport()
    for _ in range(n):
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://localhost/search")
    end = time.perf_counter()
    return end - start

async def measure_outer_loop(n):
    start = time.perf_counter()
    transport = MockTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        for _ in range(n):
            await client.get("http://localhost/search")
    end = time.perf_counter()
    return end - start

async def main():
    n = 1000
    print(f"Running {n} iterations...")

    # Warmup
    await measure_inner_loop(10)
    await measure_outer_loop(10)

    inner_time = await measure_inner_loop(n)
    print(f"Inner loop creation: {inner_time:.4f}s")

    outer_time = await measure_outer_loop(n)
    print(f"Outer loop creation: {outer_time:.4f}s")

    improvement = (inner_time - outer_time) / inner_time * 100
    print(f"Improvement: {improvement:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
