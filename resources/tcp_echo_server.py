"""Tiny localhost TCP echo server — a smoke-test target for the ComPort Zone
raw-TCP CLI (``send``/``listen``/``run``/``repl`` with ``--host``/``--tcp-port``).

Run it, then point the CLI at it:

    python resources/tcp_echo_server.py                 # 127.0.0.1:5025
    comport-zone send ping --host 127.0.0.1 --expect PONG

Per line received it replies:
    ping          -> PONG
    time          -> TIME <local timestamp>
    quit | exit   -> Bye, then closes the connection
    <anything>    -> ECHO: <anything>

The default port (5025) matches ``LanProfile``'s default, so ``--tcp-port`` is
optional. Pass ``[host] [port]`` to override. localhost-only by default.
"""

from __future__ import annotations

import socket
import sys
import threading
from datetime import datetime

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5025


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    print(f"[+] Client connected: {addr}")
    with conn:
        conn.sendall(b"TCP echo server connected.\r\n")
        while True:
            data = conn.recv(1024)
            if not data:
                print(f"[-] Client disconnected: {addr}")
                break
            text = data.decode(errors="replace").strip()
            print(f"[{addr}] RX: {text!r}")
            lowered = text.lower()
            if lowered in ("quit", "exit"):
                conn.sendall(b"Bye\r\n")
                break
            if lowered == "time":
                response = datetime.now().strftime("TIME %Y-%m-%d %H:%M:%S\r\n")
            elif lowered == "ping":
                response = "PONG\r\n"
            else:
                response = f"ECHO: {text}\r\n"
            conn.sendall(response.encode())


def main(argv: list[str]) -> int:
    host = argv[0] if len(argv) >= 1 else DEFAULT_HOST
    port = int(argv[1]) if len(argv) >= 2 else DEFAULT_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()
        print(f"TCP echo server listening on {host}:{port}")
        print("Commands: ping, time, quit. Press Ctrl+C to stop.")
        try:
            while True:
                conn, addr = server.accept()
                threading.Thread(
                    target=handle_client, args=(conn, addr), daemon=True
                ).start()
        except KeyboardInterrupt:
            print("\nShutting down.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
