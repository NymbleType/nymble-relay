"""Dual-transport server: WebSocket + Unix socket.

Handles device pairing, authentication, and streaming text input
from any connected client. Routes received text to the OutputManager
for keystroke delivery.
"""

import asyncio
import json
import logging
import os
import secrets
import socket
import string
import urllib.parse

import websockets
from websockets import serve

from .auth import TokenStore
from .protocol import (
    parse_message, build_message,
    MSG_TRANSCRIPT, MSG_STREAM_CHUNK, MSG_KEY, MSG_PING, MSG_CONFIG,
    MSG_PAIRED, MSG_AUTHENTICATED, MSG_ERROR, MSG_PONG, MSG_STATUS,
)
from .output.manager import OutputManager

logger = logging.getLogger(__name__)


def _generate_pairing_code(length: int = 6) -> str:
    """Generate a random alphanumeric pairing code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _get_local_ip() -> str:
    """Best-effort local IP detection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class RelayServer:
    """Manages WebSocket and Unix socket listeners for the relay daemon."""

    def __init__(self, config: dict, output_manager: OutputManager):
        self._config = config
        self._output = output_manager
        self._token_store = TokenStore()

        server_cfg = config.get("server", {})
        self._ws_port = server_cfg.get("ws_port", 9200)
        self._unix_socket_path = os.path.expanduser(
            server_cfg.get("unix_socket", "~/.nymble/relay.sock")
        )

        pairing_cfg = config.get("pairing", {})
        self._discovery_url = pairing_cfg.get("discovery_url", "")

        self._ws_server = None
        self._unix_server = None
        self._pairing_token: str | None = None
        self._pairing_code: str | None = None
        self._connected_clients: set = set()
        self._discovery_ws = None
        self._running = False

    @property
    def token_store(self) -> TokenStore:
        return self._token_store

    @property
    def pairing_qr_payload(self) -> str:
        """QR code payload for local pairing."""
        ip = _get_local_ip()
        return f"nymble://{ip}:{self._ws_port}?token={self._pairing_token}&name=Relay"

    async def start(self):
        """Start both WebSocket and Unix socket listeners."""
        self._running = True
        self._pairing_token = secrets.token_urlsafe(16)

        # Start WebSocket server
        self._ws_server = await serve(
            self._handle_ws_connection,
            "0.0.0.0",
            self._ws_port,
        )
        logger.info("WebSocket server listening on ws://0.0.0.0:%d", self._ws_port)

        # Start Unix socket server
        socket_dir = os.path.dirname(self._unix_socket_path)
        os.makedirs(socket_dir, exist_ok=True)
        # Remove stale socket file
        if os.path.exists(self._unix_socket_path):
            os.unlink(self._unix_socket_path)

        self._unix_server = await asyncio.start_unix_server(
            self._handle_unix_connection,
            path=self._unix_socket_path,
        )
        logger.info("Unix socket listening on %s", self._unix_socket_path)

        # Start discovery server connection if configured
        if self._discovery_url:
            asyncio.create_task(self._connect_discovery())

    async def stop(self):
        """Stop all listeners and close connections."""
        self._running = False

        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
            self._ws_server = None

        if self._unix_server:
            self._unix_server.close()
            await self._unix_server.wait_closed()
            self._unix_server = None

        for client in list(self._connected_clients):
            try:
                await client.close()
            except Exception:
                pass
        self._connected_clients.clear()

        if self._discovery_ws:
            await self._discovery_ws.close()
            self._discovery_ws = None

        # Clean up socket file
        if os.path.exists(self._unix_socket_path):
            os.unlink(self._unix_socket_path)

        logger.info("Relay server stopped")

    # --- WebSocket handling ---

    async def _handle_ws_connection(self, websocket):
        """Handle an incoming WebSocket connection."""
        # Extract path for auth
        if hasattr(websocket, "request") and hasattr(websocket.request, "path"):
            path = websocket.request.path
        elif hasattr(websocket, "path"):
            path = websocket.path
        else:
            path = ""

        # Check for pairing token (initial pairing)
        if f"token={self._pairing_token}" in path:
            remote = getattr(websocket, "remote_address", ("unknown",))[0]
            auth_token = self._token_store.generate_token(
                device_name=f"local:{remote}"
            )
            await websocket.send(build_message(
                MSG_PAIRED,
                auth_token=auth_token,
                message="Pairing successful. Use this token for future connections.",
            ))
            logger.info("Device paired (WebSocket): %s", remote)
            await self._handle_authenticated_ws(websocket, f"local:{remote}")

        # Check for auth token (returning device)
        elif "auth=" in path:
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            auth_token = params.get("auth", [None])[0]

            if auth_token:
                device_name = self._token_store.validate(auth_token)
                if device_name:
                    await websocket.send(build_message(MSG_AUTHENTICATED))
                    await self._handle_authenticated_ws(websocket, device_name)
                    return

            logger.warning("Rejected WebSocket connection: invalid auth token")
            await websocket.close(4003, "Invalid auth token")

        else:
            logger.warning("Rejected WebSocket connection: no token or auth")
            await websocket.close(4000, "Authentication required")

    async def _handle_authenticated_ws(self, websocket, device_name: str):
        """Handle streaming input from an authenticated WebSocket client."""
        self._connected_clients.add(websocket)
        # Send current status
        await websocket.send(build_message(
            MSG_STATUS,
            output=self._output.active_method,
            connected=True,
        ))
        logger.info("Streaming session started (WS): %s", device_name)

        try:
            async for message in websocket:
                response = await self._handle_message(message, source=device_name)
                if response:
                    await websocket.send(response)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._connected_clients.discard(websocket)
            logger.info("Streaming session ended (WS): %s", device_name)

    # --- Unix socket handling ---

    async def _handle_unix_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a Unix socket connection.

        Protocol: first line is the auth token, subsequent lines are JSON messages.
        """
        peer = "unix-client"
        try:
            # First line: auth token
            token_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not token_line:
                writer.close()
                return

            token = token_line.decode("utf-8", errors="replace").strip()
            device_name = self._token_store.validate(token)

            if not device_name:
                error = build_message(MSG_ERROR, message="Invalid auth token") + "\n"
                writer.write(error.encode("utf-8"))
                await writer.drain()
                writer.close()
                logger.warning("Rejected Unix socket connection: invalid token")
                return

            # Auth OK
            auth_msg = build_message(MSG_AUTHENTICATED) + "\n"
            writer.write(auth_msg.encode("utf-8"))
            await writer.drain()
            logger.info("Streaming session started (Unix): %s", device_name)

            # Read messages line by line
            while self._running:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=300.0)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    break  # EOF

                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue

                response = await self._handle_message(raw, source=device_name)
                if response:
                    writer.write((response + "\n").encode("utf-8"))
                    await writer.drain()

        except Exception as e:
            logger.error("Unix socket error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass
            logger.info("Streaming session ended (Unix): %s", peer)

    # --- Message routing ---

    async def _handle_message(self, raw: str, source: str = "unknown") -> str | None:
        """Parse and route a message from any transport.

        Returns a response message string if one should be sent back, or None.
        """
        data = parse_message(raw)
        msg_type = data.get("type")

        if msg_type == MSG_TRANSCRIPT:
            text = data.get("text", "").strip()
            if text:
                await self._on_text(text, source)
            return None

        elif msg_type == MSG_STREAM_CHUNK:
            text = data.get("text", "").strip()
            is_final = data.get("is_final", True)
            if text and is_final:
                await self._on_text(text, source)
            return None

        elif msg_type == MSG_KEY:
            key = data.get("key", "").strip()
            if key:
                await self._on_text(f"\x00KEY:{key}", source)
            return None

        elif msg_type == MSG_PING:
            return build_message(MSG_PONG)

        elif msg_type == MSG_CONFIG:
            await self._on_config_update(data)
            return build_message(MSG_STATUS, output=self._output.active_method, connected=True)

        elif msg_type == MSG_ERROR:
            logger.warning("Error message from %s: %s", source, data.get("message"))
            return None

        else:
            logger.debug("Unknown message type from %s: %s", source, msg_type)
            return None

    async def _on_text(self, text: str, source: str):
        """Deliver text via the output manager. Runs in executor to avoid blocking."""
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self._output.deliver, text)
        if not success:
            logger.warning("Failed to deliver text from %s", source)

    async def _on_config_update(self, data: dict):
        """Handle runtime config updates (typing speed, output method, etc.)."""
        if "typing_speed" in data:
            speed = data["typing_speed"]
            self._output.set_typing_speed(
                delay_ms=speed.get("delay_ms", 0),
                burst_size=speed.get("burst_size", 0),
                pre_delay_ms=speed.get("pre_delay_ms", 0),
            )

        if "output" in data:
            self._output.set_preferred(data["output"])

        logger.info("Config updated at runtime")

    # --- Discovery server ---

    async def _connect_discovery(self):
        """Connect to the discovery server for remote pairing."""
        self._pairing_code = _generate_pairing_code()
        ws_url = f"{self._discovery_url}/connect?code={self._pairing_code}&role=relay"
        logger.info("Discovery server pairing code: %s", self._pairing_code)

        while self._running:
            try:
                async with websockets.connect(ws_url) as ws:
                    self._discovery_ws = ws
                    logger.info("Connected to discovery server")

                    async for message in ws:
                        raw = message if isinstance(message, str) else message.decode()

                        try:
                            parsed = json.loads(raw)
                            if parsed.get("type") == "paired":
                                auth_token = self._token_store.generate_token(
                                    device_name="remote:discovery"
                                )
                                await ws.send(json.dumps({
                                    "type": "auth_token",
                                    "auth_token": auth_token,
                                }))
                                logger.info("Device paired via discovery server")
                                continue
                        except (json.JSONDecodeError, AttributeError):
                            pass

                        await self._handle_message(raw, source="remote:discovery")

            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                logger.warning("Discovery server connection lost (%s). Reconnecting in 5s...", e)
                self._discovery_ws = None
                if self._running:
                    await asyncio.sleep(5)
