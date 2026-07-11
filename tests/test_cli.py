"""Tests for wet_mcp.cli -- shared mcp_core CLI builder mount.

Bare invocation and any leading-dash argv start the server unchanged;
subcommands (auth/warmup/docs) run one-shot operator actions. No network
or model calls -- run_setup_sync/run_warmup/make_docs_db are mocked.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestServeDispatch:
    """Bare/flag argv route to the server unchanged."""

    def test_bare_invocation_starts_server(self):
        from wet_mcp import cli

        with (
            patch.object(sys, "argv", ["wet-mcp"]),
            patch("wet_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0

    def test_http_flag_passes_through_argv_unchanged(self):
        from wet_mcp import cli

        with (
            patch.object(sys, "argv", ["wet-mcp", "--http"]),
            patch("wet_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0


class TestAuthSubcommand:
    """`wet-mcp auth google` -- BYO client resolution + run_setup_sync."""

    def test_half_pair_flags_raise(self):
        from wet_mcp import cli

        with patch.object(
            sys, "argv", ["wet-mcp", "auth", "google", "--client-secret", "shh"]
        ):
            with pytest.raises(ValueError, match="set both together"):
                cli.main()

    def test_happy_path_sets_env_and_prints_json(self, capsys):
        from wet_mcp import cli

        result = {
            "status": "ok",
            "provider": "google_drive",
            "message": "Google Drive sync setup complete. Token saved locally.",
        }
        with (
            patch.object(
                sys,
                "argv",
                [
                    "wet-mcp",
                    "auth",
                    "google",
                    "--client-id",
                    "my-id",
                    "--client-secret",
                    "my-secret",
                ],
            ),
            patch(
                "wet_mcp.setup_tool.run_setup_sync",
                new=AsyncMock(return_value=result),
            ) as mock_setup,
            patch.dict("os.environ", {}, clear=False),
        ):
            rc = cli.main()
            import os

            assert os.environ["GOOGLE_DRIVE_CLIENT_ID"] == "my-id"
            assert os.environ["GOOGLE_DRIVE_CLIENT_SECRET"] == "my-secret"

        mock_setup.assert_awaited_once_with()
        assert rc == 0
        out = capsys.readouterr().out
        assert '"status": "ok"' in out

    def test_no_flags_skips_byo_resolution(self, capsys):
        from wet_mcp import cli

        result = {"status": "error", "provider": "google_drive", "error": "boom"}
        with (
            patch.object(sys, "argv", ["wet-mcp", "auth", "google"]),
            patch(
                "wet_mcp.setup_tool.run_setup_sync",
                new=AsyncMock(return_value=result),
            ) as mock_setup,
        ):
            rc = cli.main()

        mock_setup.assert_awaited_once_with()
        assert rc == 1


class TestWarmupSubcommand:
    """`wet-mcp warmup` -- run_warmup, no argument-taking configure."""

    def test_happy_path(self, capsys):
        from wet_mcp import cli

        result = {"status": "ok", "mode": "local", "steps": []}
        with (
            patch.object(sys, "argv", ["wet-mcp", "warmup"]),
            patch(
                "wet_mcp.setup_tool.run_warmup", new=AsyncMock(return_value=result)
            ) as mock_warmup,
        ):
            rc = cli.main()

        mock_warmup.assert_awaited_once_with()
        assert rc == 0
        assert '"mode": "local"' in capsys.readouterr().out

    def test_error_status_returns_nonzero(self):
        from wet_mcp import cli

        result = {"status": "error", "steps": []}
        with (
            patch.object(sys, "argv", ["wet-mcp", "warmup"]),
            patch("wet_mcp.setup_tool.run_warmup", new=AsyncMock(return_value=result)),
        ):
            rc = cli.main()

        assert rc == 1


class TestDocsReindexSubcommand:
    """`wet-mcp docs reindex <library>` -- standalone DocsDB, not the global."""

    def test_reindex_known_library_clears_chunks(self, capsys):
        from wet_mcp import cli

        mock_db = MagicMock()
        mock_db.get_library.return_value = {"id": "lib-1", "name": "requests"}
        mock_db.get_best_version.return_value = {"id": "ver-1"}

        with (
            patch.object(sys, "argv", ["wet-mcp", "docs", "reindex", "requests"]),
            patch("wet_mcp.server.make_docs_db", return_value=mock_db) as mock_make_db,
        ):
            rc = cli.main()

        mock_make_db.assert_called_once_with()
        mock_db.get_library.assert_called_once_with("requests")
        mock_db.get_best_version.assert_called_once_with("lib-1")
        mock_db.clear_version_chunks.assert_called_once_with("ver-1")
        assert rc == 0
        assert '"status": "cleared"' in capsys.readouterr().out

    def test_reindex_unknown_library_returns_error(self, capsys):
        from wet_mcp import cli

        mock_db = MagicMock()
        mock_db.get_library.return_value = None

        with (
            patch.object(sys, "argv", ["wet-mcp", "docs", "reindex", "ghost-lib"]),
            patch("wet_mcp.server.make_docs_db", return_value=mock_db),
        ):
            rc = cli.main()

        mock_db.get_best_version.assert_not_called()
        assert rc == 1
        assert "not found" in capsys.readouterr().out
