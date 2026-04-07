# nymble-relay

Headless text-to-keystroke relay daemon. Receives text from authenticated sources (mobile app, local STT, scripts) and types it into the active window via USB HID device, xdotool, or clipboard paste.

📖 **[Full documentation](https://nymbletype.github.io/nymble-docs/)**

## Download

Prebuilt binaries are available on the [Releases](https://github.com/NymbleType/nymble-relay/releases/latest) page:

| Platform | Download |
|----------|----------|
| Linux x86_64 | `nymble-relay-linux-x86_64` |
| macOS Apple Silicon | `nymble-relay-macos-arm64` |
| Windows x86_64 | `nymble-relay-windows-x86_64.exe` |

Download the binary for your platform, make it executable (`chmod +x` on Linux/macOS), and run it directly — no Python installation required.

```bash
# Linux / macOS
chmod +x nymble-relay-*
./nymble-relay-linux-x86_64 --help

# Windows
nymble-relay-windows-x86_64.exe --help
```

> **macOS Gatekeeper:** On first launch, macOS may block the unsigned binary. Right-click → Open, or run `xattr -d com.apple.quarantine nymble-relay-macos-arm64` to clear the flag.

## Install from PyPI

If you prefer to install as a Python package:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install nymble-relay           # clipboard + xdotool support
pip install nymble-relay[hid]      # + RP2040 USB HID support
```

Then run it:

```bash
nymble-relay --help                # show all options
nymble-relay                       # start the relay daemon
nymble-relay --generate-token      # generate an auth token
```

> **Note:** Make sure your venv is activated (`source .venv/bin/activate`) each time you open a new terminal — otherwise your shell won't find the `nymble-relay` command.

> **Why a virtual environment?** A venv keeps nymble-relay's dependencies isolated from your system Python. It's the recommended way to install any Python tool. See [Python docs on venvs](https://docs.python.org/3/library/venv.html) for more.

## Development Setup

```bash
git clone git@github.com:NymbleType/nymble-relay.git
cd nymble-relay
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows
pip install -e .
```

## Quick Start

```bash
# 1. Generate an auth token
nymble-relay --generate-token

# 2. Start the relay daemon
nymble-relay

# 3. Send text from nymble-stt
nymble-stt --destination unix --relay-token YOUR_TOKEN

# 4. Or send text from a script via Unix socket
echo "YOUR_TOKEN" | nc -N -U ~/.nymble/relay.sock
echo '{"type": "transcript", "text": "Hello world"}' | nc -N -U ~/.nymble/relay.sock
```

## Output Methods

| Method      | How it works                              | When to use                            |
|-------------|-------------------------------------------|----------------------------------------|
| `hid`       | RP2040 USB device types real keystrokes   | Secure fields, RDP, VMs, games         |
| `xdotool`   | X11 input simulation                      | Linux desktop, no hardware needed      |
| `clipboard` | Copy + paste (Cmd/Ctrl+V)                 | Universal fallback, any OS             |

**Auto mode** (default): tries `hid` → `xdotool` → `clipboard`.

## Configuration

Config files are loaded in order (each overrides the previous):

1. Bundled `config/config.yaml` (defaults)
2. `~/.nymble/relay.yaml` (user overrides)
3. `--config PATH` (explicit)
4. CLI arguments (highest priority)

```yaml
server:
  ws_port: 9200
  bind_address: "127.0.0.1"  # local only; use 0.0.0.0 for LAN access
  unix_socket: "~/.nymble/relay.sock"

output:
  method: auto        # auto | hid | clipboard | xdotool
  typing_speed:
    delay_ms: 0       # inter-key delay (0 = fastest)
    burst_size: 0     # chars per burst (0 = all at once)
    pre_delay_ms: 0   # delay before typing starts
  append_newline: false
  prefix: ""
  suffix: ""

hid:
  port: null          # null = auto-detect RP2040
  baud_rate: 115200
  timeout: 1.0

pairing:
  discovery_url: ""   # wss://your-discovery-server.com
```

## Protocol

All messages are JSON over WebSocket or Unix socket.

### Client → Relay

```json
{"type": "transcript", "text": "Hello world"}
{"type": "key", "key": "ENTER"}
{"type": "combo", "keys": ["CTRL", "A"]}
{"type": "combo", "keys": "CTRL+V"}
{"type": "speed", "ms": 50}
{"type": "delay", "ms": 1000}
{"type": "hold", "key": "SHIFT"}
{"type": "release"}
{"type": "sequence", "steps": [{"text": "hello"}, {"key": "ENTER"}, {"delay": 500}]}
{"type": "ping"}
{"type": "config", "typing_speed": {"delay_ms": 50}}
```

Plain text (non-JSON) is treated as text to type — no JSON required for simple use.

### Relay → Client

```json
{"type": "paired", "auth_token": "..."}
{"type": "authenticated"}
{"type": "status", "output": "hid", "connected": true}
{"type": "error", "message": "..."}
{"type": "pong"}
```

### Authentication

**WebSocket:** Pass token as URL parameter:
- First connection (pairing): `ws://host:9200?token=PAIRING_TOKEN`
- Returning device: `ws://host:9200?auth=AUTH_TOKEN`

**Unix socket:** Send token as the first line, then JSON messages:
```
AUTH_TOKEN\n
{"type": "transcript", "text": "Hello"}\n
```

## Scripting Examples

You don't need a special client to talk to the relay. Any tool that speaks WebSocket or Unix sockets will work.

### websocat

[websocat](https://github.com/vi/websocat) is a lightweight WebSocket CLI (`cargo install websocat` or grab a binary from releases):

```bash
TOKEN="your-auth-token"

# One-shot: type text and disconnect
echo '{"type": "transcript", "text": "Hello from websocat"}' \
  | websocat "ws://127.0.0.1:9200?auth=$TOKEN"

# Interactive session (type JSON lines, Ctrl+C to quit)
websocat "ws://127.0.0.1:9200?auth=$TOKEN"

# Plain text works too — no JSON needed
echo "Just type this" | websocat "ws://127.0.0.1:9200?auth=$TOKEN"
```

### Unix socket with netcat

No WebSocket needed for local scripts — the Unix socket is simpler:

```bash
TOKEN="your-auth-token"

# One-liner: auth + type text
printf '%s\n%s\n' "$TOKEN" '{"type": "transcript", "text": "Hello from nc"}' \
  | nc -N -U ~/.nymble/relay.sock

# Plain text (after auth line)
printf '%s\n%s\n' "$TOKEN" "Just type this" \
  | nc -N -U ~/.nymble/relay.sock
```

### Python one-liner

```bash
python3 -c "
import asyncio, websockets, sys
async def send():
    async with websockets.connect('ws://127.0.0.1:9200?auth=$TOKEN') as ws:
        await ws.send(sys.argv[1])
asyncio.run(send())
" '{"type": "transcript", "text": "Hello from Python"}'
```

### Bash function

Drop this in your `.bashrc` for a quick `ntype` command:

```bash
# Type text via nymble-relay (uses Unix socket)
ntype() {
  local token="your-auth-token"
  printf '%s\n{"type": "transcript", "text": "%s"}\n' "$token" "$*" \
    | nc -N -U ~/.nymble/relay.sock
}

# Usage:
# ntype Hello world
# ntype "This is a sentence."
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│ nymble-stt  │────▶│             │     │  RP2040 HID  │──▶ keystrokes
│ (local/cloud│     │             │────▶│  (USB serial) │
│  whisper)   │     │ nymble-relay│     └──────────────┘
└─────────────┘     │             │     ┌──────────────┐
┌─────────────┐     │  WebSocket  │────▶│   xdotool    │──▶ X11 input
│ mobile app  │────▶│  + Unix sock│     └──────────────┘
│ (Flutter)   │     │             │     ┌──────────────┐
└─────────────┘     │             │────▶│  clipboard   │──▶ paste
                    └─────────────┘     └──────────────┘
```

## License

MIT
