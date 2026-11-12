"""Regression tests for the PHP built-in-server WordPress router."""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTER = REPO_ROOT / "wordpress" / "router.php"


def test_router_delegates_existing_directories():
    """Keep /wp-admin/ on its own index instead of the WordPress front page."""
    source = ROUTER.read_text()
    assert "file_exists( __DIR__ . $path )" in source
    assert "! is_dir( __DIR__ . $path )" not in source


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP is not installed")
def test_router_handles_admin_static_and_pretty_routes(tmp_path):
    """Exercise the router through the same PHP server used by the README."""
    shutil.copy2(ROUTER, tmp_path / "router.php")
    (tmp_path / "index.php").write_text("<?php echo 'front';")
    admin = tmp_path / "wp-admin"
    admin.mkdir()
    (admin / "index.php").write_text("<?php echo 'admin';")
    (tmp_path / "asset.txt").write_text("asset")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    process = subprocess.Popen(
        [shutil.which("php"), "-S", f"127.0.0.1:{port}", "router.php"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                _, error = process.communicate()
                pytest.fail(f"PHP test server exited during startup: {error}")
            try:
                if requests.get(f"{base_url}/", timeout=0.2).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.05)
        else:
            pytest.fail("PHP test server did not start")

        assert requests.get(f"{base_url}/wp-admin/", timeout=2).text == "admin"
        assert requests.get(f"{base_url}/asset.txt", timeout=2).text == "asset"
        assert requests.get(f"{base_url}/pretty-permalink/", timeout=2).text == "front"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
