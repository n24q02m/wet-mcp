import asyncio
import os
import time
import tracemalloc
from pathlib import Path

from aiohttp import web

from wet_mcp.sources.crawler import download_media

# Create a large file
LARGE_FILE_SIZE = 10 * 1024 * 1024  # 10MB
LARGE_FILE_PATH = Path("large_file.bin")


def create_large_file():
    if not LARGE_FILE_PATH.exists():
        with open(LARGE_FILE_PATH, "wb") as f:
            f.write(os.urandom(LARGE_FILE_SIZE))


async def handle(request):
    return web.FileResponse(LARGE_FILE_PATH)


async def start_server():
    app = web.Application()
    app.router.add_get("/large", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8080)
    await site.start()
    return runner


async def main():
    create_large_file()
    runner = await start_server()

    urls = [
        f"http://localhost:8080/large?{i}" for i in range(20)
    ]  # 20 files = 200MB total
    output_dir = Path("bench_downloads")

    tracemalloc.start()
    start_time = time.time()

    await download_media(urls, str(output_dir), concurrency=5)

    end_time = time.time()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Time: {end_time - start_time:.2f}s")
    print(f"Peak Memory: {peak / 1024 / 1024:.2f} MB")

    await runner.cleanup()

    # Cleanup
    for f in output_dir.glob("*"):
        f.unlink()
    output_dir.rmdir()
    LARGE_FILE_PATH.unlink()


if __name__ == "__main__":
    asyncio.run(main())
