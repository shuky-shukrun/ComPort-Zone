"""Local tutorial instrument. TCP and UDP on 127.0.0.1:5025; no hardware.

Run: python tools/media/demo_device.py [--port 5025]
Queries reply with CRLF. Writes are silent, as on a typical SCPI instrument.
"""
from __future__ import annotations

import argparse
import math
import socketserver
import threading
from contextlib import contextmanager


class DemoInstrument:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.voltage = 12.0
        self.output = True
        self.fault = False
        self.sample = 0

    def reply(self, command: str) -> str | None:
        with self.lock:
            command = command.strip()
            upper = command.upper()
            if upper == "*IDN?":
                return "ComPort Zone,Demo PSU,DEMO-001,1.0"
            if upper == "PING":
                return "PONG"
            if upper == "*RST":
                self.voltage, self.output, self.fault, self.sample = 12.0, True, False, 0
                return None
            if upper == "VOLT?":
                return f"{self.voltage:.3f}"
            if upper == "OUTP?":
                return str(int(self.output))
            if upper == "STAT?":
                return "FAULT" if self.fault else "READY"
            if upper == "SYST:ERR?":
                return '0,"No error"'
            if upper in {"MEAS:VOLT?", "MEAS:CURR?", "MEAS:TEMP?"}:
                self.sample += 1
                ripple = math.sin(self.sample / 7)
                value = {
                    "MEAS:VOLT?": self.voltage + 0.04 * ripple if self.output else 0,
                    "MEAS:CURR?": 0.42 + 0.025 * ripple if self.output else 0,
                    "MEAS:TEMP?": (65 if self.fault else 28) + ripple,
                }[upper]
                return f"{value:.3f}"
            if upper.startswith("VOLT "):
                try:
                    value = float(command.split(maxsplit=1)[1])
                    if math.isfinite(value) and 0 <= value <= 24:
                        self.voltage = value
                except ValueError:
                    pass
            if upper in {"OUTP ON", "OUTP 1", "OUTP OFF", "OUTP 0"}:
                self.output = upper in {"OUTP ON", "OUTP 1"}
            if upper in {"DEMO:FAULT ON", "DEMO:FAULT OFF"}:
                self.fault = upper.endswith(" ON")
            # Unknown commands deliberately time out, useful for EXPECT demos.
            return None


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TCPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        # readline handles fragmented and coalesced TCP packets correctly.
        while line := self.rfile.readline(65537):
            if len(line) > 65536:
                return
            response = self.server.instrument.reply(line.decode("utf-8", errors="replace"))
            if response is not None:
                self.wfile.write((response + "\r\n").encode())
                self.wfile.flush()


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        for command in data.decode("utf-8", errors="replace").splitlines():
            response = self.server.instrument.reply(command)
            if response is not None:
                sock.sendto((response + "\r\n").encode(), self.client_address)


@contextmanager
def running_demo(port: int = 5025):
    """Share one instrument between TCP and UDP; port=0 supports isolated tests."""
    instrument = DemoInstrument()
    tcp = TCPServer(("127.0.0.1", port), TCPHandler)
    try:
        udp = socketserver.ThreadingUDPServer(tcp.server_address, UDPHandler)
    except BaseException:
        tcp.server_close()
        raise
    udp.daemon_threads = True
    threads = []
    try:
        for server in (tcp, udp):
            server.instrument = instrument
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            threads.append(thread)
        yield instrument, tcp.server_address[1]
    finally:
        for server in (tcp, udp):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5025)
    args = parser.parse_args()
    try:
        with running_demo(args.port) as (_, port):
            print(f"Tutorial device: TCP + UDP 127.0.0.1:{port}. Ctrl+C to stop.", flush=True)
            threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
