from pathlib import Path
import os

p = Path("/usr/bin/python3")
print(f"Path: {p}")
print(f"String: {str(p)}")
print(f"As posix: {p.as_posix()}")
