from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_windows_launchers_wire_setup_start_shortcut_and_package_scripts() -> None:
    expected_files = [
        "setup-windows.cmd",
        "start-windows.cmd",
        "install-shortcut-windows.cmd",
        "scripts/setup-windows.ps1",
        "scripts/start-windows.ps1",
        "scripts/install-shortcut-windows.ps1",
        "scripts/package-windows.ps1",
    ]

    for path in expected_files:
        assert (ROOT / path).exists(), path

    setup_cmd = read_repo_file("setup-windows.cmd")
    start_cmd = read_repo_file("start-windows.cmd")
    shortcut_cmd = read_repo_file("install-shortcut-windows.cmd")
    setup_ps1 = read_repo_file("scripts/setup-windows.ps1")
    start_ps1 = read_repo_file("scripts/start-windows.ps1")
    shortcut_ps1 = read_repo_file("scripts/install-shortcut-windows.ps1")
    package_ps1 = read_repo_file("scripts/package-windows.ps1")

    assert "scripts\\setup-windows.ps1" in setup_cmd
    assert "scripts\\start-windows.ps1" in start_cmd
    assert "scripts\\install-shortcut-windows.ps1" in shortcut_cmd
    assert "config\\settings.example.env" in setup_ps1
    assert 'uv pip install -e "."' in setup_ps1
    assert "npm --prefix apps/desktop/web install" in setup_ps1
    assert "uvicorn betexplorer_scraper.api:app" in start_ps1
    assert "npm --prefix apps/desktop/web run dev" in start_ps1
    assert "http://127.0.0.1:3000" in start_ps1
    assert "BetExplorer Monitor.lnk" in shortcut_ps1
    assert "apps\\desktop\\src-tauri\\icons\\icon.ico" in shortcut_ps1
    assert "BetExplorer-Monitor-Client.zip" in package_ps1


def test_unix_launchers_wire_setup_start_and_shortcut_scripts() -> None:
    expected_files = [
        "setup-unix.sh",
        "start-unix.sh",
        "install-shortcut-unix.sh",
        "scripts/setup-unix.sh",
        "scripts/start-unix.sh",
        "scripts/install-shortcut-unix.sh",
    ]

    for path in expected_files:
        assert (ROOT / path).exists(), path

    setup = read_repo_file("scripts/setup-unix.sh")
    start = read_repo_file("scripts/start-unix.sh")
    shortcut = read_repo_file("scripts/install-shortcut-unix.sh")

    assert "config/settings.example.env" in setup
    assert 'uv pip install -e "."' in setup
    assert "npm --prefix apps/desktop/web install" in setup
    assert "uvicorn betexplorer_scraper.api:app" in start
    assert "npm --prefix apps/desktop/web run dev" in start
    assert "http://127.0.0.1:3000" in start
    assert "BetExplorer Monitor.command" in shortcut
    assert "BetExplorer Monitor.desktop" in shortcut


def test_client_launch_guide_has_nontechnical_steps() -> None:
    guide = read_repo_file("RUNNING_FOR_CLIENT.md")

    assert "Windows" in guide
    assert "macOS / Linux" in guide
    assert "setup-windows.cmd" in guide
    assert "start-windows.cmd" in guide
    assert "install-shortcut-windows.cmd" in guide
    assert "start-unix.sh" in guide
    assert "http://127.0.0.1:3000" in guide
