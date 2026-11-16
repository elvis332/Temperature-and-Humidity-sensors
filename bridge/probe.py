"""Read all four holding registers without the EMS or database."""
import argparse
import socket
import struct

def read(host="127.0.0.1", port=1502, unit=1):
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(struct.pack(">HHHBBHH", 1, 0, 6, unit, 3, 0, 4))
        f = sock.makefile("rb")
        tid, protocol, length, uid = struct.unpack(">HHHB", f.read(7))
        pdu = f.read(length-1)
        if pdu[0] == 0x83:
            raise RuntimeError(f"Modbus exception 0x{pdu[1]:02x}: sensor unavailable")
        if (tid, protocol, uid, pdu[:2]) != (1, 0, unit, b"\x03\x08"):
            raise RuntimeError("Unexpected Modbus reply")
        t, h, b, lqi = struct.unpack(">hHHH", pdu[2:])
        return {"temperature_c": t/10, "humidity_pct": h/10, "battery_pct": b, "lqi": lqi}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1502)
    p.add_argument("--unit", type=int, default=1)
    print(read(**vars(p.parse_args())))
