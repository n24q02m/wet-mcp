import signal
import subprocess
import unittest
from unittest.mock import MagicMock, patch

# We need to import the module to test, but we will patch the functions in it
from wet_mcp import searxng_runner


class TestProcessKilling(unittest.TestCase):
    @patch("wet_mcp.searxng_runner.os.killpg")
    @patch("wet_mcp.searxng_runner.os.getpgid")
    @patch("wet_mcp.searxng_runner.os.kill")
    def test_kill_pid_unix_graceful(self, mock_kill, mock_getpgid, mock_killpg):
        with patch("wet_mcp.searxng_runner.sys.platform", "linux"):
            proc = MagicMock(spec=subprocess.Popen)
            proc.pid = 1234
            proc.poll.return_value = None

            # We need to patch time.sleep or subprocess.Popen.wait to not block
            proc.wait.side_effect = subprocess.TimeoutExpired(cmd="foo", timeout=3)

            mock_getpgid.return_value = 1234

            searxng_runner._force_kill_process(proc)

            # Verify it tried to killpg SIGTERM
            mock_killpg.assert_any_call(1234, signal.SIGTERM)
            # Verify it tried to killpg SIGKILL (since we simulated timeout)
            mock_killpg.assert_any_call(1234, signal.SIGKILL)

    @patch("wet_mcp.searxng_runner.os.kill")
    def test_kill_pid_windows(self, mock_kill):
        with patch("wet_mcp.searxng_runner.sys.platform", "win32"):
            proc = MagicMock(spec=subprocess.Popen)
            proc.pid = 1234
            proc.poll.return_value = None
            proc.wait.side_effect = subprocess.TimeoutExpired(cmd="foo", timeout=3)

            searxng_runner._force_kill_process(proc)

            # On Windows it uses _kill_pid which calls os.kill(pid, signal.SIGTERM)
            # It calls it twice: once for initial attempt, once for force attempt (after timeout)
            assert mock_kill.call_count == 2
            mock_kill.assert_called_with(1234, signal.SIGTERM)

            # It should NOT call proc.terminate() or proc.kill() directly anymore
            assert not proc.terminate.called
            assert not proc.kill.called

    @patch("wet_mcp.searxng_runner.subprocess.run")
    @patch("wet_mcp.searxng_runner.os.kill")
    def test_kill_stale_unix(self, mock_kill, mock_run):
        with patch("wet_mcp.searxng_runner.sys.platform", "linux"):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "1234\n5678\n"

            # Mock os.getpid to avoid killing self
            with patch("wet_mcp.searxng_runner.os.getpid", return_value=5678):
                # Mock os.getpgid because _kill_pid calls it
                with patch("wet_mcp.searxng_runner.os.getpgid", return_value=1234):
                    # Mock os.killpg because _kill_pid calls it
                    with patch("wet_mcp.searxng_runner.os.killpg") as mock_killpg:
                        searxng_runner._kill_stale_port_process(8080)

                        # _kill_pid calls os.killpg
                        mock_killpg.assert_any_call(1234, signal.SIGTERM)

                        # Should NOT kill 5678 (self)
                        assert (5678, signal.SIGTERM) not in [
                            args[0] for args in mock_killpg.call_args_list
                        ]

    @patch("wet_mcp.searxng_runner.subprocess.run")
    @patch("wet_mcp.searxng_runner.os.kill")
    def test_kill_stale_windows(self, mock_kill, mock_run):
        with patch("wet_mcp.searxng_runner.sys.platform", "win32"):
            mock_run.return_value.stdout = "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       1234"

            searxng_runner._kill_stale_port_process(8080)

            # Should kill 1234 via os.kill
            mock_kill.assert_called_with(1234, signal.SIGTERM)
