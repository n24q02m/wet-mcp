"""Tests for wet_mcp.cli -- shared mcp_core CLI builder mount.

Bare invocation and any leading-dash argv start the server unchanged;
subcommands (auth/warmup/docs) run one-shot operator actions. No network
or model calls -- run_setup_sync/run_warmup/make_docs_db are mocked.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch


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

    def test_half_pair_flags_returns_clean_error(self, capsys):
        from wet_mcp import cli

        with patch.object(
            sys, "argv", ["wet-mcp", "auth", "google", "--client-secret", "shh"]
        ):
            rc = cli.main()

        assert rc == 2
        err = capsys.readouterr().err
        assert "set both together" in err
        assert "shh" not in err  # never print the secret value

    def test_happy_path_threads_byo_pair_to_setup_google_auth(self, capsys):
        """auth google --client-id/--client-secret must reach setup_google_auth.

        wet_mcp.config.settings is a module-level singleton resolved at
        import time, so a prior regression wrote the BYO pair to os.environ
        (a no-op -- the singleton was already frozen) instead of threading
        it through run_setup_sync's params. This does NOT blanket-mock
        run_setup_sync: it lets the real function run (including its
        missing-credentials check) and only mocks the network-touching
        setup_google_auth, so the assertion below proves the pair actually
        reaches that call rather than being silently dropped.
        """
        from wet_mcp import cli

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
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_setup_google_auth,
        ):
            rc = cli.main()

        mock_setup_google_auth.assert_awaited_once_with(
            client_id="my-id", client_secret="my-secret"
        )
        assert rc == 0
        assert '"status": "ok"' in capsys.readouterr().out

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


class TestUnknownSubcommand:
    """build_cli's own unrecognized-subcommand handling -- rc 2, no server start."""

    def test_unknown_subcommand_returns_rc_2(self, capsys):
        from wet_mcp import cli

        with (
            patch.object(sys, "argv", ["wet-mcp", "bogus"]),
            patch("wet_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_not_called()
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err


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


class TestLogoutSubcommand:
    """`wet-mcp logout` -- clears the local Google Drive sync token."""

    def test_clears_saved_token(self, capsys):
        from wet_mcp import cli

        with (
            patch.object(sys, "argv", ["wet-mcp", "logout"]),
            patch(
                "wet_mcp.token_store.load_token", return_value={"refresh_token": "x"}
            ),
            patch("wet_mcp.token_store.delete_token") as mock_delete,
        ):
            rc = cli.main()

        mock_delete.assert_called_once_with("google_drive")
        assert rc == 0
        assert "cleared" in capsys.readouterr().out.lower()

    def test_nothing_to_clear(self, capsys):
        from wet_mcp import cli

        with (
            patch.object(sys, "argv", ["wet-mcp", "logout"]),
            patch("wet_mcp.token_store.load_token", return_value=None),
            patch("wet_mcp.token_store.delete_token") as mock_delete,
        ):
            rc = cli.main()

        mock_delete.assert_not_called()
        assert rc == 0
        assert "nothing to log out" in capsys.readouterr().out.lower()


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
