"""Tests for standalone CLI tools (test_client.py).

Validates module imports, argument parser definitions, and help formatting
to guard against regressions in developer CLI utilities.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_test_client_help_invocable() -> None:
    """Test that test_client.py runs --help without import or syntax errors."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "test_client.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0
    assert "Hisense VIDAA Integration CLI Test Tool" in result.stdout
    assert "report" in result.stdout
    assert "probe" in result.stdout
    assert "text" in result.stdout
    assert "state" in result.stdout
    assert "source" in result.stdout
    assert "--text" in result.stdout
    assert "--text-action" in result.stdout
    assert "--verify-ssl" in result.stdout
    assert "--probe" in result.stdout


def test_cli_tools_syntax_and_import() -> None:
    """Test importing test_client module directly from scripts/."""
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    import test_client

    assert callable(test_client.main)
    assert callable(test_client.do_send_text)
    assert callable(test_client.do_state)
    assert callable(test_client.do_change_source)


def test_do_send_text_mocked(monkeypatch) -> None:
    """Test do_send_text connects and dispatches send_text_input."""
    from unittest.mock import MagicMock
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import test_client

    mock_client = MagicMock()
    mock_client.connected = True
    monkeypatch.setattr(test_client, "create_client_from_creds", lambda *a, **k: mock_client)

    test_client.do_send_text({"ip_address": "192.168.1.50"}, "Blade Runner", action="insert")

    mock_client.connect_and_run.assert_called_once()
    mock_client.send_text_input.assert_called_once_with("Blade Runner", action="insert")
    mock_client.disconnect.assert_called_once()

