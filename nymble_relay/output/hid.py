"""HID device output — send text to RP2040 for keystroke injection.

Optional output method. Requires the RP2040 HID device connected via USB serial.

Firmware protocol:
  TYPE:<text>        → OK:TYPED   — type text as keystrokes
  KEY:<name>         → OK:KEY     — send a special key (ENTER, TAB, etc.)
  COMBO:<key+key>    → OK:COMBO   — press a key combination (CTRL+A, etc.)
  HOLD:<key>         → OK:HOLD    — hold a key down
  RELEASE            → OK:RELEASE — release all held keys
  SPEED:<ms>         → OK:SPEED   — set firmware-level inter-key delay
  DELAY:<ms>         → OK:DELAY   — pause for N milliseconds
  PING               → OK:PONG    — keepalive
"""

import logging
import time

logger = logging.getLogger(__name__)

# Detection priority for auto-detect:
# 1. "Nymble" in description — our firmware (any board)
# 2. Known Pico/CircuitPython vendor IDs (fallback for unflashed boot.py)
NYMBLE_IDENTIFIER = "Nymble"
PICO_VIDS = {0x2E8A, 0x239A}
CIRCUITPY_DESCRIPTIONS = ["CircuitPython", "Pico"]


class HidOutput:
    """Sends text to an RP2040 HID device over USB serial."""

    def __init__(self, port: str | None = None, baud_rate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial = None

    @classmethod
    def from_config(cls, config: dict) -> "HidOutput":
        hid_cfg = config.get("hid", {})
        return cls(
            port=hid_cfg.get("port"),
            baud_rate=hid_cfg.get("baud_rate", 115200),
            timeout=hid_cfg.get("timeout", 1.0),
        )

    def connect(self) -> bool:
        """Open serial connection to the HID device. Returns True on success."""
        try:
            import serial
            import serial.tools.list_ports
        except ImportError:
            logger.error("pyserial is required for HID output: pip install nymble-relay[hid]")
            return False

        port = self.port or self._auto_detect_port()
        if not port:
            logger.warning("No RP2040 HID device found.")
            return False

        try:
            self._serial = serial.Serial(port, self.baud_rate, timeout=self.timeout)
            # Wait for CircuitPython to boot and start code.py
            time.sleep(2)
            # Flush any startup output
            if self._serial.in_waiting:
                self._serial.read(self._serial.in_waiting)

            # Try ping up to 3 times (CircuitPython may need a moment)
            for attempt in range(3):
                if self.ping():
                    logger.info("Connected to HID device on %s", port)
                    return True
                logger.debug("Ping attempt %d failed, retrying...", attempt + 1)
                time.sleep(0.5)

            logger.warning("HID device on %s did not respond to ping after 3 attempts", port)
            return False
        except Exception as e:
            logger.error("Failed to connect to HID device on %s: %s", port, e)
            self._serial = None
            return False

    def _auto_detect_port(self) -> str | None:
        """Try to find the RP2040 serial port automatically."""
        try:
            import serial.tools.list_ports
        except ImportError:
            return None

        nymble_port = None
        fallback_port = None

        for port_info in serial.tools.list_ports.comports():
            desc = port_info.description or ""
            # Priority 1: Nymble firmware identifier
            if NYMBLE_IDENTIFIER in desc:
                version = self._parse_firmware_version(desc)
                if version:
                    logger.info("Detected Nymble HID firmware %s on %s", version, port_info.device)
                else:
                    logger.info("Detected Nymble HID device on %s", port_info.device)
                nymble_port = port_info.device
                break
            # Priority 2: Known Pico/CircuitPython VIDs or descriptions
            if not fallback_port:
                if port_info.vid in PICO_VIDS:
                    fallback_port = port_info.device
                elif any(kw in desc for kw in CIRCUITPY_DESCRIPTIONS):
                    fallback_port = port_info.device

        if nymble_port:
            return nymble_port
        if fallback_port:
            logger.debug("No Nymble-identified device; falling back to Pico/CircuitPython detection")
            return fallback_port
        return None

    @staticmethod
    def _parse_firmware_version(description: str) -> str | None:
        """Extract version from a Nymble USB product string like 'Nymble HID v0.2.0'."""
        if " v" in description:
            return description.split(" v", 1)[1].strip()
        return None

    def _send_command(self, command: str) -> str | None:
        """Send a command to the RP2040 and return the response line.

        Returns the response string on success, None on failure.
        """
        if not self._serial:
            return None
        try:
            self._serial.write(f"{command}\n".encode("utf-8"))
            self._serial.flush()
            response = self._serial.readline().decode("utf-8", errors="replace").strip()
            return response
        except Exception as e:
            logger.error("Serial command failed (%s): %s", command.split(":")[0], e)
            return None

    def ping(self) -> bool:
        """Send a PING to the RP2040 and check for OK:PONG response."""
        response = self._send_command("PING")
        return response == "OK:PONG"

    def type_text(self, text: str) -> bool:
        """Send text to be typed as keystrokes by the HID device."""
        response = self._send_command(f"TYPE:{text}")
        return response is not None and response.startswith("OK:")

    def type_char(self, char: str) -> bool:
        """Type a single character. Used for per-key timing control from OutputManager."""
        return self.type_text(char)

    def send_key(self, key_name: str) -> bool:
        """Send a special key (ENTER, TAB, ESC, etc.) to the HID device."""
        response = self._send_command(f"KEY:{key_name}")
        return response is not None and response.startswith("OK:")

    def send_combo(self, keys: list[str] | str) -> bool:
        """Send a key combination (e.g., CTRL+A, ALT+TAB).

        Accepts either a list of key names or a '+'-joined string.
        """
        if isinstance(keys, list):
            combo_str = "+".join(keys)
        else:
            combo_str = keys
        response = self._send_command(f"COMBO:{combo_str}")
        return response is not None and response.startswith("OK:")

    def hold_key(self, key_name: str) -> bool:
        """Press and hold a key (released by release_keys or next RELEASE command)."""
        response = self._send_command(f"HOLD:{key_name}")
        return response is not None and response.startswith("OK:")

    def release_keys(self) -> bool:
        """Release all held keys on the HID device."""
        response = self._send_command("RELEASE")
        return response is not None and response.startswith("OK:")

    def set_speed(self, delay_ms: int) -> bool:
        """Set the firmware-level inter-key delay in milliseconds.

        0 = fastest (no delay between keystrokes).
        """
        response = self._send_command(f"SPEED:{delay_ms}")
        return response is not None and response.startswith("OK:")

    def send_delay(self, delay_ms: int) -> bool:
        """Tell the firmware to pause for N milliseconds.

        The firmware blocks and responds with OK:DELAY when done.
        Max 30 seconds (capped by firmware).
        """
        # Increase serial timeout for long delays
        old_timeout = self._serial.timeout if self._serial else 1.0
        if self._serial and delay_ms > 1000:
            self._serial.timeout = (delay_ms / 1000.0) + 2.0

        response = self._send_command(f"DELAY:{delay_ms}")

        # Restore timeout
        if self._serial:
            self._serial.timeout = old_timeout

        return response is not None and response.startswith("OK:")

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def name(self) -> str:
        return "hid"

    def disconnect(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Disconnected from HID device")

    @staticmethod
    def available() -> bool:
        """Check if pyserial is installed."""
        try:
            import serial
            return True
        except ImportError:
            return False
