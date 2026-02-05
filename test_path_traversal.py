from pathlib import Path

def test_traversal():
    output_dir = Path("/tmp/safe_dir")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Simulate malicious URL part
    malicious_part = ".."

    # pathlib behavior
    filepath = output_dir / malicious_part
    print(f"Joined path: {filepath}")
    print(f"Resolved path: {filepath.resolve()}")

    # Check if it escaped
    try:
        if not filepath.resolve().is_relative_to(output_dir.resolve()):
            print("VULNERABILITY CONFIRMED: Path traversal possible!")
        else:
            print("Safe: Path is inside output_dir")
    except ValueError:
         print("VULNERABILITY CONFIRMED: Path traversal possible (relative check failed)!")

    # Another case: what if filename has slashes?
    # url.split("/")[-1] guarantees no forward slashes.
    # But what about backslashes on Windows? Or encoded characters?

    # If URL is http://example.com/..
    url = "http://example.com/.."
    filename = url.split("/")[-1].split("?")[0] or "download"
    print(f"Filename from '{url}': '{filename}'")

    filepath = output_dir / filename
    print(f"Joined path: {filepath}")
    print(f"Resolved path: {filepath.resolve()}")

    if not filepath.resolve().is_relative_to(output_dir.resolve()):
        print("VULNERABILITY CONFIRMED with '..' filename!")

if __name__ == "__main__":
    test_traversal()
