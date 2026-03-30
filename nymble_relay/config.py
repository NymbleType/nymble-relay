"""Configuration loader for nymble-relay.

Load order (each layer overrides the previous):
1. Bundled config/config.yaml (package defaults)
2. ~/.nymble/relay.yaml (user overrides)
3. Explicit --config path
4. CLI arguments override all
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Bundled default config (relative to package)
_BUNDLED_CONFIG = Path(__file__).parent.parent / "config" / "config.yaml"
_USER_CONFIG = Path.home() / ".nymble" / "relay.yaml"

DEFAULT_CONFIG: dict = {
    "server": {
        "ws_port": 9200,
        "unix_socket": "~/.nymble/relay.sock",
    },
    "output": {
        "method": "auto",
        "typing_speed": {
            "delay_ms": 0,
            "burst_size": 0,
            "pre_delay_ms": 0,
        },
        "append_newline": False,
        "prefix": "",
        "suffix": "",
    },
    "hid": {
        "port": None,
        "baud_rate": 115200,
        "timeout": 1.0,
    },
    "pairing": {
        "discovery_url": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to load config %s: %s", path, e)
        return {}


def load_config(config_path: str | None = None, cli_overrides: dict | None = None) -> dict:
    """Load configuration with the standard merge order.

    Args:
        config_path: Explicit config file path (from --config).
        cli_overrides: Dict of CLI argument overrides to apply last.

    Returns:
        Merged configuration dict.
    """
    config = DEFAULT_CONFIG.copy()

    # Layer 1: bundled defaults
    bundled = _load_yaml(_BUNDLED_CONFIG)
    if bundled:
        config = _deep_merge(config, bundled)
        logger.debug("Loaded bundled config from %s", _BUNDLED_CONFIG)

    # Layer 2: user config
    user = _load_yaml(_USER_CONFIG)
    if user:
        config = _deep_merge(config, user)
        logger.debug("Loaded user config from %s", _USER_CONFIG)

    # Layer 3: explicit config path
    if config_path:
        explicit = _load_yaml(Path(config_path))
        if explicit:
            config = _deep_merge(config, explicit)
            logger.debug("Loaded explicit config from %s", config_path)

    # Layer 4: CLI overrides
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)

    return config
