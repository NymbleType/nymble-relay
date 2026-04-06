"""nymble-relay entry point.

Usage:
  nymble-relay                          Start the relay daemon
  nymble-relay --generate-token         Generate an auth token and exit
  nymble-relay --list-devices           List paired devices and exit
  nymble-relay --revoke-all             Revoke all tokens and exit
"""

import argparse
import asyncio
import logging
import signal
import sys

from .auth import TokenStore
from .config import load_config
from .output.manager import OutputManager
from .server import RelayServer

logger = logging.getLogger("nymble_relay")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nymble-relay",
        description="Headless text-to-keystroke relay daemon",
    )
    parser.add_argument("--config", metavar="PATH", help="Config file path")
    parser.add_argument("--port", type=int, metavar="PORT", help="WebSocket listen port (default: 9200)")
    parser.add_argument(
        "--bind", metavar="ADDR",
        help="Bind address (default: 127.0.0.1). Use 0.0.0.0 for LAN access.",
    )
    parser.add_argument("--socket", metavar="PATH", help="Unix socket path (default: ~/.nymble/relay.sock)")
    parser.add_argument(
        "--output", choices=["hid", "clipboard", "xdotool", "auto"],
        help="Output method (default: auto)",
    )
    parser.add_argument("--generate-token", action="store_true", help="Generate an auth token and exit")
    parser.add_argument("--list-devices", action="store_true", help="List paired devices and exit")
    parser.add_argument("--revoke-all", action="store_true", help="Revoke all tokens and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _handle_token_commands(args: argparse.Namespace) -> bool:
    """Handle --generate-token, --list-devices, --revoke-all. Returns True if handled."""
    store = TokenStore()

    if args.generate_token:
        token = store.generate_token(device_name="cli")
        print(f"Generated auth token:\n\n  {token}\n")
        print("Use this token to authenticate clients connecting to the relay.")
        return True

    if args.list_devices:
        devices = store.list_devices()
        if not devices:
            print("No paired devices.")
        else:
            print(f"{len(devices)} paired device(s):\n")
            for d in devices:
                last = d["last_used"]
                last_str = f"last used {last}" if last else "never used"
                print(f"  • {d['name']} ({last_str})")
        return True

    if args.revoke_all:
        store.revoke_all()
        print("All tokens revoked.")
        return True

    return False


async def _run(config: dict):
    """Main async entry point — start the relay daemon."""
    output = OutputManager(config)
    if not output.connect():
        logger.error("No output method available. Exiting.")
        sys.exit(1)

    server = RelayServer(config, output)
    await server.start()

    logger.info("nymble-relay running (output: %s)", output.active_method)
    logger.info("Generate a token: nymble-relay --generate-token")

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await stop_event.wait()
    await server.stop()
    output.disconnect()


def main():
    args = parse_args()
    _setup_logging(args.verbose)

    if _handle_token_commands(args):
        return

    # Build CLI overrides
    cli_overrides: dict = {}
    if args.port:
        cli_overrides.setdefault("server", {})["ws_port"] = args.port
    if args.bind:
        cli_overrides.setdefault("server", {})["bind_address"] = args.bind
    if args.socket:
        cli_overrides.setdefault("server", {})["unix_socket"] = args.socket
    if args.output:
        cli_overrides.setdefault("output", {})["method"] = args.output

    config = load_config(config_path=args.config, cli_overrides=cli_overrides)

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
