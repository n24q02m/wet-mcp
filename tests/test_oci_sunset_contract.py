"""Contracts for retiring public OCI publication while retaining CF deploys."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _job_block(workflow: str, job: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"  {job}:")
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", line):
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def test_cd_releases_registry_artifacts_without_public_oci_jobs():
    workflow = _read(".github/workflows/cd.yml")

    assert "  build-docker:" not in workflow
    assert "  merge-docker:" not in workflow
    assert "docker/login-action" not in workflow
    assert "docker/build-push-action" not in workflow
    assert "dockerhub-description" not in workflow
    assert "DOCKERHUB_IMAGE" not in workflow
    assert "GHCR_IMAGE" not in workflow
    assert "packages: write" not in workflow

    registry = _job_block(workflow, "publish-mcp-registry")
    assert "needs: [release, publish-pypi]" in registry
    assert "needs: merge-docker" not in registry

    marketplace = _job_block(workflow, "sync-marketplace")
    assert "needs: [release, publish-mcp-registry]" in marketplace


def test_cloudflare_deploy_remains_release_independent_of_public_oci_jobs():
    workflow = _read(".github/workflows/cd.yml")
    deploy = _job_block(workflow, "deploy-cf")

    assert "needs: [release]" in deploy
    assert "deploy_cf.py --from-template" in deploy
    assert "IMAGE_TAG:" in deploy
    assert "merge-docker" not in deploy


def test_server_metadata_publishes_pypi_only():
    metadata = json.loads(_read("server.json"))

    assert metadata["packages"]
    assert {package["registryType"] for package in metadata["packages"]} == {"pypi"}
    assert all(package["runtimeHint"] == "uvx" for package in metadata["packages"])


def test_self_host_docs_build_images_from_source():
    readme = _read("README.md")
    passport = _read("docs/passport.md")
    compose = _read("docker-compose.yml")
    wrangler = _read("wrangler.jsonc")

    assert "docker build --target http -t wet-mcp:local ." in readme
    assert "Public OCI image publication is discontinued" in readme
    assert "Existing historical registry tags" in readme
    assert "wet-mcp:local" in readme
    assert "build: ." in compose
    assert "docker build --target http --build-arg SLIM=1 -t wet-mcp:beta ." in readme
    assert "docker build --target http --build-arg SLIM=1 -t wet-mcp:beta ." in wrangler
    assert "wrangler containers push wet-mcp:beta" in readme
    assert "wrangler containers push wet-mcp:beta" in wrangler
    assert "docker build --target http -t wet-mcp:local ." in passport
    assert "wet-mcp:local" in passport


def test_no_public_current_image_aliases_or_registry_claims_remain():
    public_surfaces = (
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "server.json",
        "docker-compose.yml",
        "docs/passport.md",
        ".github/workflows/cd.yml",
        "wrangler.jsonc",
        "src/wet_mcp/transport_check.py",
        "src/worker.ts",
    )
    forbidden = re.compile(
        r"(?:docker\.io|ghcr\.io|hub\.docker\.com|dockerhub)|"
        r"n24q02m/wet-mcp:(?:latest|beta|stable)",
        re.IGNORECASE,
    )

    hits = [
        relative for relative in public_surfaces if forbidden.search(_read(relative))
    ]
    assert not hits, f"public OCI reference remains in: {', '.join(hits)}"


def test_release_guidance_names_only_pypi_and_internal_cf_path():
    for relative in ("AGENTS.md", "CLAUDE.md"):
        guidance = _read(relative)
        assert "PyPI (uv publish) -> MCP Registry" in guidance
        assert "DockerHub" not in guidance
        assert "GHCR" not in guidance
        assert "registry.cloudflare.com" in guidance
