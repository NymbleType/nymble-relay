"""Output routing — decides how to deliver text to the active window.

Supports HID (RP2040 USB), xdotool (X11), and clipboard (fallback).
Auto mode priority: hid > xdotool > clipboard.
"""

import asyncio
import logging
import time

from .hid import HidOutput
from .clipboard import ClipboardOutput
from .xdotool import XdotoolOutput

logger = logging.getLogger(__name__)


class OutputManager:
    """Routes text to the appropriate output backend with optional timing control."""

    def __init__(self, config: dict):
        self._config = config
        output_cfg = config.get("output", {})
        self._append_newline = output_cfg.get("append_newline", False)
        self._prefix = output_cfg.get("prefix", "")
        self._suffix = output_cfg.get("suffix", "")

        # Typing speed
        speed_cfg = output_cfg.get("typing_speed", {})
        self._delay_ms = speed_cfg.get("delay_ms", 0)
        self._burst_size = speed_cfg.get("burst_size", 0)
        self._pre_delay_ms = speed_cfg.get("pre_delay_ms", 0)

        # Initialize backends
        self._clipboard = ClipboardOutput()
        self._xdotool = XdotoolOutput()
        self._hid: HidOutput | None = None

        # Determine preferred output
        self._preferred = output_cfg.get("method", "auto")

        if self._preferred in ("hid", "auto"):
            self._hid = HidOutput.from_config(config)

    def set_preferred(self, method: str):
        """Change the preferred output method at runtime."""
        self._preferred = method
        if method in ("hid", "auto") and not self._hid:
            self._hid = HidOutput.from_config(self._config)

    def set_typing_speed(self, delay_ms: int = 0, burst_size: int = 0, pre_delay_ms: int = 0):
        """Update typing speed parameters at runtime."""
        self._delay_ms = delay_ms
        self._burst_size = burst_size
        self._pre_delay_ms = pre_delay_ms
        logger.info("Typing speed updated: delay=%dms burst=%d pre_delay=%dms",
                     delay_ms, burst_size, pre_delay_ms)

    def try_connect_hid(self) -> bool:
        """Attempt to connect to HID device. Returns True on success.

        Safe to call repeatedly — creates a fresh HidOutput if needed.
        """
        if self._preferred not in ("hid", "auto"):
            return False
        if self._hid and self._hid.connected:
            return True
        # Create a fresh instance in case the old one is stale
        self._hid = HidOutput.from_config(self._config)
        if self._hid.connect():
            logger.info("HID device connected — switching output to HID")
            return True
        return False

    def connect(self) -> bool:
        """Connect to output devices. Returns True if at least one is available."""
        # Try HID first
        if self._preferred in ("hid", "auto") and self._hid:
            if self._hid.connect():
                logger.info("Output: HID device (serial) — keystrokes via RP2040")
                return True
            if self._preferred == "hid":
                logger.error("HID device required but not found")
                return False
            logger.info("No HID device detected, trying xdotool...")

        # Try xdotool
        if self._preferred in ("xdotool", "auto"):
            if XdotoolOutput.available():
                logger.info("Output: xdotool — X11 keystroke simulation")
                return True
            if self._preferred == "xdotool":
                logger.error("xdotool required but not installed")
                return False
            logger.info("xdotool not available, falling back to clipboard")

        # Clipboard fallback
        if ClipboardOutput.available():
            logger.info("Output: clipboard paste")
            return True

        logger.error("No output method available")
        return False

    def deliver(self, text: str) -> bool:
        """Deliver text via the active output method.

        Special prefix \\x00KEY: routes to send_key instead of type_text.
        Applies typing speed settings for HID and xdotool backends.
        """
        # Handle special key commands
        if text.startswith("\x00KEY:"):
            key_name = text[5:]
            return self.send_key(key_name)

        full_text = f"{self._prefix}{text}{self._suffix}"

        # Try HID first
        if self._preferred in ("hid", "auto") and self._hid and self._hid.connected:
            success = self._deliver_with_timing(full_text, backend="hid")
            if success and self._append_newline:
                self._hid.send_key("ENTER")
            if success:
                return True
            # IMPORTANT: Do NOT fall back after HID attempt. The HID device
            # types keystrokes immediately before responding — if the response
            # is lost/garbled, the text was already typed. Falling back to
            # xdotool would type it a second time.
            logger.warning("HID output failed (text may have been partially typed)")
            return False

        # Try xdotool
        if self._preferred in ("xdotool", "auto") and XdotoolOutput.available():
            success = self._deliver_with_timing(full_text, backend="xdotool")
            if success and self._append_newline:
                self._xdotool.send_key("ENTER")
            if success:
                return True
            logger.warning("xdotool output failed, falling back to clipboard")

        # Clipboard fallback — always pastes all at once
        if self._delay_ms > 0:
            logger.debug("Clipboard ignores typing speed — pasting all at once")
        if self._append_newline:
            full_text += "\n"
        return self._clipboard.type_text(full_text)

    def _deliver_with_timing(self, text: str, backend: str) -> bool:
        """Deliver text with optional per-character or burst timing.

        If delay_ms is 0, sends the entire text at once (fastest).
        If delay_ms > 0, splits text into characters or bursts and types with delays.
        """
        if self._pre_delay_ms > 0:
            time.sleep(self._pre_delay_ms / 1000.0)

        # No timing — send all at once
        if self._delay_ms <= 0:
            if backend == "hid":
                return self._hid.type_text(text)
            elif backend == "xdotool":
                return self._xdotool.type_text(text)
            return False

        # xdotool has native delay support
        if backend == "xdotool":
            return self._xdotool.type_text(text, delay_ms=self._delay_ms)

        # HID: split into characters or bursts
        if self._burst_size > 0:
            # Type in bursts
            for i in range(0, len(text), self._burst_size):
                chunk = text[i:i + self._burst_size]
                if not self._hid.type_text(chunk):
                    return False
                if i + self._burst_size < len(text):
                    time.sleep(self._delay_ms / 1000.0)
        else:
            # Type character by character
            for char in text:
                if not self._hid.type_char(char):
                    return False
                time.sleep(self._delay_ms / 1000.0)

        return True

    def send_key(self, key_name: str) -> bool:
        """Send a special key (ENTER, TAB, etc.)."""
        if self._hid and self._hid.connected:
            return self._hid.send_key(key_name)
        if XdotoolOutput.available():
            return self._xdotool.send_key(key_name)
        logger.warning("Key command '%s' requires HID or xdotool output", key_name)
        return False

    def send_combo(self, keys) -> bool:
        """Send a key combination (e.g., ["CTRL", "A"] or "CTRL+A")."""
        if self._hid and self._hid.connected:
            return self._hid.send_combo(keys)
        if XdotoolOutput.available():
            # xdotool combo: convert to xdotool key format
            if isinstance(keys, list):
                combo_str = "+".join(keys)
            else:
                combo_str = keys
            return self._xdotool.send_key(combo_str)
        logger.warning("Combo command requires HID or xdotool output")
        return False

    def hold_key(self, key_name: str) -> bool:
        """Press and hold a key (HID only)."""
        if self._hid and self._hid.connected:
            return self._hid.hold_key(key_name)
        logger.warning("Hold command requires HID output")
        return False

    def release_keys(self) -> bool:
        """Release all held keys (HID only)."""
        if self._hid and self._hid.connected:
            return self._hid.release_keys()
        logger.warning("Release command requires HID output")
        return True  # Not an error if nothing to release

    def set_device_speed(self, delay_ms: int) -> bool:
        """Set the firmware-level inter-key delay on the HID device."""
        if self._hid and self._hid.connected:
            return self._hid.set_speed(delay_ms)
        logger.warning("Speed command requires HID output")
        return False

    def send_delay(self, delay_ms: int) -> bool:
        """Pause the HID device for N milliseconds."""
        if self._hid and self._hid.connected:
            return self._hid.send_delay(delay_ms)
        # Fallback: sleep locally
        import time
        time.sleep(min(delay_ms, 30000) / 1000.0)
        return True

    def execute_sequence(self, steps: list) -> bool:
        """Execute a scripted sequence of steps.

        Each step is a dict with one action key:
          {"type": "text"}     — type text
          {"key": "ENTER"}     — press a key
          {"combo": [...]}     — key combination
          {"delay": 1000}      — pause in ms
          {"speed": 50}        — set typing speed in ms
          {"hold": "SHIFT"}    — hold a key
          {"release": true}    — release all keys

        Speed resets to 0 (fastest) after the sequence completes.
        """
        speed_changed = False

        for i, step in enumerate(steps):
            try:
                if "type" in step:
                    self.deliver(step["type"])
                elif "text" in step:
                    self.deliver(step["text"])
                elif "key" in step:
                    self.send_key(step["key"])
                elif "combo" in step:
                    self.send_combo(step["combo"])
                elif "delay" in step:
                    self.send_delay(int(step["delay"]))
                elif "speed" in step:
                    self.set_device_speed(int(step["speed"]))
                    speed_changed = True
                elif "hold" in step:
                    self.hold_key(step["hold"])
                elif "release" in step:
                    self.release_keys()
                else:
                    logger.warning("Unknown sequence step %d: %s", i, step)
            except Exception as e:
                logger.error("Sequence step %d failed: %s", i, e)
                # Reset speed and release keys on error
                if speed_changed:
                    self.set_device_speed(0)
                self.release_keys()
                return False

        # Reset speed after sequence
        if speed_changed:
            self.set_device_speed(0)

        return True

    @property
    def active_method(self) -> str:
        """Return the name of the currently active output method."""
        if self._preferred in ("hid", "auto") and self._hid and self._hid.connected:
            return "hid"
        if self._preferred in ("xdotool", "auto") and XdotoolOutput.available():
            return "xdotool"
        return "clipboard"

    def disconnect(self):
        """Clean up output connections."""
        if self._hid:
            self._hid.disconnect()
