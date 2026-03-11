## 2024-05-28 - Command Execution Risk with user-provided port
**Vulnerability:** Argument injection via f-string formatting (`f":{port}"`) in `subprocess.run` inside `_kill_stale_port_process` if the `port` variable contains malicious strings, bypassing the lack of `shell=True`.
**Learning:** Always validate and safely cast external input (like casting `port` to an `int`) before interpolating it into command line arguments, even when `shell=True` is not used.
**Prevention:** Strictly enforce integer typing `int(port)` before using it in shell-executed parameters, and run `pytest` to ensure functionality is preserved.
