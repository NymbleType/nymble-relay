"""xdotool-based text output — type into the active window via X11 input simulation.

Linux-focused. Uses xdotool for keystroke simulation without clipboard involvement.
This means it works in contexts where clipboard paste doesn't (some terminal emulators,
games, etc.) but requires an X11 display.

Platform extension notes:
  - macOS: could use cliclick (brew install cliclick)
  - Windows: could use PowerShell SendKeys or AutoHotkey
  - Wayland: xdotool doesn't work; would need ydotool or wtype
"""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


class XdotoolOutput:
    """Types text into the active window using xdotool."""

    def __init__(self):
        self._xdotool_path: str | None = shutil.which("xdotool")

    def type_text(self, text: str, delay_ms: int = 0) -> bool:
        """Type text using xdotool.

        Args:
            text: Text to type.
            delay_ms: Inter-key delay in milliseconds (0 = xdotool default, ~12ms).

        Returns:
            True on success.
        """
        if not self._xdotool_path:
            logger.error("xdotool is not installed")
            return False
        try:
            cmd = [self._xdotool_path, "type"]
            if delay_ms > 0:
                cmd.extend(["--delay", str(delay_ms)])
            cmd.append(text)
            subprocess.run(cmd, check=True, timeout=30)
            return True
        except subprocess.TimeoutExpired:
            logger.error("xdotool type timed out")
            return False
        except Exception as e:
            logger.error("xdotool type failed: %s", e)
            return False

    def type_char(self, char: str) -> bool:
        """Type a single character using xdotool."""
        return self.type_text(char)

    def send_key(self, key: str) -> bool:
        """Send a special key (Return, Tab, Escape, etc.) using xdotool.

        Args:
            key: Key name as xdotool understands it (e.g., "Return", "Tab", "Escape").
                 Common mappings from our protocol: ENTER→Return, TAB→Tab, ESC→Escape.
        """
        if not self._xdotool_path:
            logger.error("xdotool is not installed")
            return False

        # Map our protocol key names to xdotool key names
        key_map = {
            "ENTER": "Return",
            "TAB": "Tab",
            "ESC": "Escape",
            "ESCAPE": "Escape",
            "BACKSPACE": "BackSpace",
            "DELETE": "Delete",
            "SPACE": "space",
            "UP": "Up",
            "DOWN": "Down",
            "LEFT": "Left",
            "RIGHT": "Right",
        }
        xdotool_key = key_map.get(key.upper(), key)

        try:
            subprocess.run(
                [self._xdotool_path, "key", xdotool_key],
                check=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.error("xdotool key '%s' failed: %s", key, e)
            return False

    @property
    def name(self) -> str:
        return "xdotool"

    @staticmethod
    def available() -> bool:
        """Check if xdotool is installed."""
        return shutil.which("xdotool") is not None
