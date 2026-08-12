"""Tiny localhost UDP echo server — a smoke-test target for the ComPort Zone
UDP CLI (``send``/``listen``/``run``/``repl`` with ``--udp-host``/``--udp-port``).

Run it, then point the CLI at it:

    python resources/udp_echo_server.py                     # 127.0.0.1:5025
    comport-zone send ping --udp-host 127.0.0.1 --expect PONG

Per datagram received it replies:
    ping          -> PONG
    time          -> TIME <local timestamp>
    <anything>    -> ECHO: <anything>

Unlike the TCP twin there is no connection and no ``quit`` command: stop it
with Ctrl+C. Replies are sent **without** a trailing CR/LF on purpose — that is
what a datagram device usually does, and it exercises the whole-datagram
framing (``DatagramMatcher``) that the UDP transport defaults to.

The default port (5025) matches ``UdpProfile``'s default, so ``--udp-port`` is
optional. Pass ``[host] [port]`` to override. localhost-only by default.
"""

from __future__ import annotations

import socket
import sys
from datetime import datetime

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5025
# Any legal IPv4 datagram; oversized reads are discarded by Windows, not truncated.
MAX_DATAGRAM = 65535


def reply_for(text: str) -> str:
    lowered = text.lower()
    if lowered == "time":
        return datetime.now().strftime("TIME %Y-%m-%d %H:%M:%S")
    if lowered == "ping":
        return "PONG"
    return f"ECHO: {text}"


def main(argv: list[str]) -> int:
    host = argv[0] if len(argv) >= 1 else DEFAULT_HOST
    port = int(argv[1]) if len(argv) >= 2 else DEFAULT_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((host, port))
        print(f"UDP echo server listening on {host}:{port}")
        print("Commands: ping, time. Press Ctrl+C to stop.")
        try:
            while True:
                payload, peer = server.recvfrom(MAX_DATAGRAM)
                text = payload.decode(errors="replace").strip()
                print(f"[{peer}] RX: {text!r}")
                server.sendto(reply_for(text).encode(), peer)
        except KeyboardInterrupt:
            print("\nShutting down.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
