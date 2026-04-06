"""Wire protocol for relay communication.

All messages are JSON. Supported types:

Input (client → relay):
  {"type": "transcript", "text": "..."}                              — type this text
  {"type": "stream_chunk", "text": "...", "is_final": true/false}    — streaming
  {"type": "key", "key": "ENTER"}                                    — special keystroke
  {"type": "combo", "keys": ["CTRL", "A"]}                          — key combination
  {"type": "combo", "keys": "CTRL+V"}                               — combo as string
  {"type": "sequence", "steps": [...]}                               — scripted sequence
  {"type": "speed", "ms": 50}                                       — set typing speed
  {"type": "delay", "ms": 1000}                                     — pause
  {"type": "hold", "key": "SHIFT"}                                  — hold a key
  {"type": "release"}                                                — release held keys
  {"type": "ping"}                                                   — keepalive
  {"type": "config", "typing_speed": {...}}                          — update config at runtime

Output (relay → client):
  {"type": "paired", "auth_token": "..."}           — initial pairing response
  {"type": "authenticated"}                         — auth confirmed
  {"type": "status", "output": "hid", "connected": true}  — status update
  {"type": "error", "message": "..."}               — error
  {"type": "pong"}                                  — ping response
"""

import json
import logging

logger = logging.getLogger(__name__)

# Message type constants — input (client → relay)
MSG_TRANSCRIPT = "transcript"
MSG_STREAM_CHUNK = "stream_chunk"
MSG_KEY = "key"
MSG_COMBO = "combo"
MSG_SEQUENCE = "sequence"
MSG_SPEED = "speed"
MSG_DELAY = "delay"
MSG_HOLD = "hold"
MSG_RELEASE = "release"
MSG_PING = "ping"
MSG_CONFIG = "config"

# Message type constants — output (relay → client)
MSG_PAIRED = "paired"
MSG_AUTHENTICATED = "authenticated"
MSG_STATUS = "status"
MSG_ERROR = "error"
MSG_PONG = "pong"

# All known types for validation
KNOWN_INPUT_TYPES = {
    MSG_TRANSCRIPT, MSG_STREAM_CHUNK, MSG_KEY, MSG_COMBO, MSG_SEQUENCE,
    MSG_SPEED, MSG_DELAY, MSG_HOLD, MSG_RELEASE, MSG_PING, MSG_CONFIG,
}
KNOWN_OUTPUT_TYPES = {MSG_PAIRED, MSG_AUTHENTICATED, MSG_STATUS, MSG_ERROR, MSG_PONG}


def parse_message(raw: str) -> dict:
    """Parse a raw JSON message string into a dict.

    Returns the parsed dict on success. On failure, returns
    {"type": "error", "message": "..."} with the parse error.
    Falls back to treating plain text as a transcript message.
    """
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"type": MSG_TRANSCRIPT, "text": str(data)}
        if "type" not in data:
            # No type field — treat as transcript if text is present
            if "text" in data:
                data["type"] = MSG_TRANSCRIPT
            else:
                return {"type": MSG_ERROR, "message": "Missing 'type' field"}
        return data
    except json.JSONDecodeError:
        # Plain text — treat as raw transcript
        text = raw.strip()
        if text:
            return {"type": MSG_TRANSCRIPT, "text": text}
        return {"type": MSG_ERROR, "message": "Empty message"}


def build_message(msg_type: str, **kwargs) -> str:
    """Build a JSON message string from a type and keyword arguments.

    Example:
        build_message("paired", auth_token="abc123")
        → '{"type": "paired", "auth_token": "abc123"}'
    """
    data = {"type": msg_type, **kwargs}
    return json.dumps(data)
