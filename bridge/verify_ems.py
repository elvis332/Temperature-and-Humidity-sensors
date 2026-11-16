"""Verify actual EMS reader and UI patch from source ZIP. Never extract .env or start EMS."""
import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
import yaml
from .bridge import Cache, Handler, Server

ROOT = Path(__file__).resolve().parents[1]
FILES = ("backend/app/devices/modbus_tcp_source.py", "backend/app/telemetry/source.py",
         "backend/app/api/routes/environment.py", "frontend/src/pages/EnvironmentPage.jsx",
         "frontend/src/pages/DevicesPage.jsx", "config/profiles/WTR10E.yaml")

def verify(archive):
    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(archive) as source_zip:
        root = Path(folder)
        for name in FILES:
            matches = [n for n in source_zip.namelist() if n == name or n.endswith("/" + name)]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one source file: {name}")
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source_zip.read(matches[0]))
        sys.path.insert(0, str(root))
        from backend.app.devices.modbus_tcp_source import ModbusTCPSource
        points = yaml.safe_load((ROOT / "config/profiles/SNZB02D.yaml").read_text(encoding="utf-8"))["points"]
        wired = yaml.safe_load((root / "config/profiles/WTR10E.yaml").read_text(encoding="utf-8-sig"))["points"]
        for actual, original in zip(points[:2], wired):
            assert actual["key"] == original["key"]
            for field in ("register_address", "register_type", "scale", "function_code"):
                assert actual["source"][field] == original["source"][field], field
        cache = Cache([{"unit_id": u, "topic": f"sander-test/{u}", "offline_seconds": 30} for u in (1, 2)])
        cache.connection(True)
        with Server(("127.0.0.1", 0), Handler) as server:
            server.cache = cache
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def source(unit):
                    return ModbusTCPSource({"device": {"id": f"TH-{unit+1:02d}"}, "communication": {
                        "ip_address": "127.0.0.1", "port": server.server_address[1], "modbus_unit_id": unit}},
                        {"points": points})
                def send(unit, temp):
                    cache.update(f"sander-test/{unit}", json.dumps({
                        "temperature": temp, "humidity": 61.2, "battery": 20, "linkquality": 180, "_simulated": True}))
                def check(unit, temp):
                    actual = {p["key"]: p["value"] for p in source(unit).read()["points"]}
                    assert actual == {"temperature_c": temp, "humidity_pct": 61.2, "battery_pct": 20, "lqi": 180}, actual
                def unavailable(unit):
                    try:
                        source(unit).read()
                    except RuntimeError as exc:
                        assert "11" in str(exc), str(exc)
                    else:
                        raise AssertionError("Unavailable sensor returned data")
                send(1, -2.5)
                send(2, 26.3)
                check(1, -2.5)
                check(2, 26.3)
                cache.seen[1] = time.time() - 31
                unavailable(1)
                check(2, 26.3)
                send(1, 25.6)
                check(1, 25.6)
                cache.connection(False)
                unavailable(1)
                print("PASS: actual EMS reader, four registers, two units, offline, recovery, broker loss")
            finally:
                server.shutdown()
                thread.join()
        subprocess.run([sys.executable, str(ROOT / "integrations/modbus/apply_ui.py"), str(root), "--apply"], check=True)
        api = root / "backend/app/api/routes/environment.py"
        compile(api.read_text(encoding="utf-8"), str(api), "exec")
        assert "BatteryIcon" in (root / "frontend/src/pages/EnvironmentPage.jsx").read_text(encoding="utf-8")
        print("PASS: UI patch applied; backend syntax valid. Frontend build still required.")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    verify(p.parse_args().archive)
