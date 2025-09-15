"""
Pytest configuration and fixtures for service-driven testing.

This adds the ability to:
- Provide service/system connection data from a JSON file or environment variables
- Select one or many systems to test against via CLI or env var
- Enable/disable integration tests with a flag

CLI options:
- --services-file: Path to a JSON file describing systems (default resolves to tests/services.json or tests/services.example.json)
- --systems: Comma-separated list of system names to include (or 'all' for all enabled). Default from env CRESNEXTWS_SYSTEMS.
- --run-integration: Enable integration tests (they're skipped by default).

Environment variables:
- CRESNEXTWS_SERVICES_FILE: Path to services JSON file.
- CRESNEXTWS_SYSTEMS: Comma-separated systems to include (or 'all').

The services file supports ${ENV_VAR} placeholders which will be substituted
from the environment at load time.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

from cresnextws import ClientConfig, CresNextWSClient


ENV_SERVICES_FILE = "CRESNEXTWS_SERVICES_FILE"
ENV_SYSTEMS = "CRESNEXTWS_SYSTEMS"


def _default_services_path() -> Optional[Path]:
    """Resolve the default services file path if present.

    Priority order:
    1) tests/services.json
    2) tests/services.example.json
    """
    candidates = [
        Path(__file__).parent / "services.json",
        Path(__file__).parent / "services.example.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("cresnextws")
    default_file = os.environ.get(ENV_SERVICES_FILE)
    if not default_file:
        p = _default_services_path()
        default_file = str(p) if p else ""

    group.addoption(
        "--services-file",
        action="store",
        default=default_file,
        help=(
            "Path to JSON file containing service systems. "
            f"Env: {ENV_SERVICES_FILE}."
        ),
    )
    group.addoption(
        "--systems",
        action="store",
        default=os.environ.get(ENV_SYSTEMS, ""),
        help=(
            "Comma-separated system names to include, or 'all' for all enabled. "
            f"Env: {ENV_SYSTEMS}."
        ),
    )
    group.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Enable integration tests that connect to real systems",
    )
    group.addoption(
        "--integration-delay",
        action="store",
        type=float,
        default=1.0,
        help="Delay in seconds between integration tests (default: 1.0)",
    )


def pytest_configure(config: pytest.Config) -> None:
    # Declare markers to avoid PytestUnknownMarkWarning
    config.addinivalue_line("markers", "integration: marks tests that hit real systems")


def pytest_runtest_teardown(item: pytest.Item, nextitem: Optional[pytest.Item]) -> None:
    """Add delay between integration tests if configured."""
    # Check if the current test is an integration test
    if item.get_closest_marker("integration") is not None:
        # Get the integration delay setting
        delay = item.config.getoption("--integration-delay")
        if delay > 0 and nextitem is not None:
            # Only add delay if there's a next test to run
            # Check if the next test is also an integration test
            if nextitem.get_closest_marker("integration") is not None:
                time.sleep(delay)


def _env_substitute(value: Any) -> Any:
    """Recursively substitute ${VARS} in strings from environment.

    - If value is a str, replace ${VAR} with os.environ.get('VAR', '').
    - If dict or list, recurse.
    - Else, return as-is.
    """
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")

        return pattern.sub(repl, value)
    if isinstance(value, list):
        return [_env_substitute(v) for v in value]
    if isinstance(value, dict):
        return {k: _env_substitute(v) for k, v in value.items()}
    return value


def _load_services_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return _env_substitute(data)  # type: ignore[return-value]


def _select_system_names(services: Dict[str, Any], systems_arg: str) -> List[str]:
    systems = services.get("systems", {}) or {}
    if not systems:
        return []

    if systems_arg and systems_arg.strip().lower() != "all":
        requested = {s.strip() for s in systems_arg.split(",") if s.strip()}
        return [name for name in systems.keys() if name in requested]

    # Default to all enabled systems (enabled defaults to True if missing)
    names: List[str] = []
    for name, cfg in systems.items():
        enabled = cfg.get("enabled", True)
        if enabled:
            names.append(name)
    return names


@pytest.fixture(scope="session")
def services_config(pytestconfig: pytest.Config) -> Dict[str, Any]:
    """Load the overall services configuration dict from JSON.

    Returns an empty dict if file isn't provided or found.
    """
    file_opt = pytestconfig.getoption("--services-file")
    if not file_opt:
        return {}

    path = Path(file_opt)
    if not path.exists():
        # Be tolerant; empty config means no param from services
        return {}
    try:
        return _load_services_json(path)
    except Exception as exc:  # pragma: no cover - defensive
        pytest.exit(f"Failed to load services file '{path}': {exc}")


@pytest.fixture(scope="session")
def selected_system_names(pytestconfig: pytest.Config, services_config: Dict[str, Any]) -> List[str]:
    systems_arg: str = pytestconfig.getoption("--systems") or ""
    return _select_system_names(services_config, systems_arg)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize tests that request 'service_name' across selected systems.

    Reads config directly from CLI/environment to avoid relying on fixtures here.
    """
    if "service_name" in metafunc.fixturenames:
        config = metafunc.config
        services_file = config.getoption("--services-file") or ""
        services: Dict[str, Any] = {}
        if services_file:
            p = Path(services_file)
            if p.exists():
                try:
                    services = _load_services_json(p)
                except Exception:
                    services = {}

        systems_arg: str = config.getoption("--systems") or ""
        names = _select_system_names(services or {}, systems_arg)

        # If no systems were selected or found, parametrize with empty to skip such tests
        metafunc.parametrize("service_name", names if names else [], scope="session")


@pytest.fixture(scope="session")
def system_config(service_name: str, services_config: Dict[str, Any]) -> Dict[str, Any]:
    systems = services_config.get("systems", {}) or {}
    cfg = systems.get(service_name, {})
    if not cfg:
        pytest.skip(f"System '{service_name}' not found in services config")
    if not cfg.get("enabled", True):
        pytest.skip(f"System '{service_name}' is disabled in services config")
    return cfg


@pytest.fixture(scope="session")
def client_config(system_config: Dict[str, Any]) -> ClientConfig:
    # Map system_config into ClientConfig fields
    return ClientConfig(
    host=system_config.get("host", "test.local"),
    username=(system_config.get("auth", {}) or {}).get("username", "u"),
    password=(system_config.get("auth", {}) or {}).get("password", "p"),
    ignore_self_signed=bool(system_config.get("ignore_self_signed", True)),
    auto_reconnect=bool(system_config.get("auto_reconnect", False)),
    auth_path=system_config.get("auth_path", "/userlogin.html"),
    websocket_path=system_config.get("websocket_path", "/websockify"),
    ws_ping_interval=float(system_config.get("ws_ping_interval", 30.0)),
    reconnect_delay=float(system_config.get("reconnect_delay", 1.0)),
    )


@pytest.fixture(scope="session")
def credentials(system_config: Dict[str, Any]) -> Dict[str, Optional[str]]:
    auth = system_config.get("auth", {}) or {}
    return {
        "username": auth.get("username"),
        "password": auth.get("password"),
    }


@pytest_asyncio.fixture()
async def client(pytestconfig: pytest.Config, client_config: ClientConfig, credentials: Dict[str, Optional[str]]):
    """Integration fixture that yields a connected client to the selected system.

    Skips if --run-integration is not set.
    """
    if not pytestconfig.getoption("--run-integration"):
        pytest.skip("Integration tests are disabled. Use --run-integration to enable.")

    c = CresNextWSClient(client_config)
    try:
        await c.connect()
        yield c
    finally:
        await c.disconnect()
