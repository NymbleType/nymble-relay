"""Clipboard-based text output — paste into the active input window.

Default output method. No extra hardware required.
Copies text to the system clipboard and simulates a paste keystroke.
"""

import logging
import platform
import subprocess
import time

logger = logging.getLogger(__name__)


class ClipboardOutput:
    """Inserts text into the active window via clipboard copy + simulated paste."""

    def __init__(self):
        self._system = platform.system()

    def type_text(self, text: str) -> bool:
        """Copy text to clipboard and simulate paste (Cmd+V / Ctrl+V).

        Returns True on success.
        """
        try:
            self._set_clipboard(text)
            time.sleep(0.05)  # Small delay for clipboard to settle
            self._simulate_paste()
            return True
        except Exception as e:
            logger.error("Clipboard output failed: %s", e)
            return False

    def _set_clipboard(self, text: str):
        """Copy text to the system clipboard."""
        if self._system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        elif self._system == "Linux":
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"), check=True,
                )
            except FileNotFoundError:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"), check=True,
                )
        elif self._system == "Windows":
            subprocess.run(
                ["powershell", "-command", f"Set-Clipboard -Value '{text}'"],
                check=True,
            )
        else:
            raise RuntimeError(f"Unsupported platform: {self._system}")

    def _simulate_paste(self):
        """Simulate Cmd+V (macOS) or Ctrl+V (Linux/Windows)."""
        if self._system == "Darwin":
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to keystroke "v" using command down'
            ], check=True)
        elif self._system == "Linux":
            subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
        elif self._system == "Windows":
            subprocess.run([
                "powershell", "-command",
                'Add-Type -AssemblyName System.Windows.Forms; '
                '[System.Windows.Forms.SendKeys]::SendWait("^v")'
            ], check=True)

    @property
    def name(self) -> str:
        return "clipboard"

    @staticmethod
    def available() -> bool:
        """Check if clipboard output is likely to work on this system."""
        system = platform.system()
        if system == "Darwin":
            return True
        elif system == "Linux":
            try:
                subprocess.run(["which", "xclip"], capture_output=True, check=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                try:
                    subprocess.run(["which", "xsel"], capture_output=True, check=True)
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    return False
        elif system == "Windows":
            return True
        return False
