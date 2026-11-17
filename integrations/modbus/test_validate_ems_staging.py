import tempfile
import unittest
from pathlib import Path

from integrations.modbus.validate_ems_staging import inspect_staging


class StagingSourceContract(unittest.TestCase):
    def test_missing_source_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            result = inspect_staging(folder)
            self.assertFalse(result["ready_for_runtime_acceptance"])
            self.assertTrue(result["errors"])
            self.assertIn("staging SQL reads/writes", result["not_tested"])

    def test_matching_disposable_integration_is_source_ready_only(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            root2 = Path(folder)
            paths = {
                "backend/app/api/routes/environment.py":
                    'sensor = {"zigbee":True, "battery_pct":100, "battery_low_pct":20, "offline_grace_seconds":120}\n',
                "frontend/src/pages/EnvironmentPage.jsx":
                    'import BatteryIcon from "./BatteryIcon";\nconst x=sensor.battery_pct;\nconst y=sensor.battery_low_pct;\n',
                "frontend/src/pages/BatteryIcon.jsx":
                    'export default function BatteryIcon({value,threshold}) { return null; }\n',
                "config/profiles/SNZB02D.yaml":
                    (root / "config/profiles/SNZB02D.yaml").read_text(encoding="utf-8"),
                "config/profiles/WTR10E.yaml":
                    "profile: {id: WTR10E}\n",
            }
            for name, contents in paths.items():
                path = root2 / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            result = inspect_staging(root2)
            self.assertTrue(result["ready_for_runtime_acceptance"], result["errors"])
            self.assertIn("server reboot and power recovery", result["not_tested"])


if __name__ == "__main__":
    unittest.main()
