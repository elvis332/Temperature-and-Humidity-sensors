import { useEffect, useState } from "react";
import { getZigbeeMaintenance, setZigbeePairing, setZigbeeDeviceOption } from "../api";
import { useI18n } from "../i18n";

const CALIBRATIONS = ["temperature_calibration", "humidity_calibration"];

export default function ZigbeeMaintenancePanel({ gatewayId, online, devices, onRefresh }) {
  const { t } = useI18n();
  const [capabilities, setCapabilities] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [ieee, setIeee] = useState("");
  const [key, setKey] = useState(CALIBRATIONS[0]);
  const [value, setValue] = useState("0");
  const sensors = devices.filter((d) => d.model === "SNZB-02D" && /^0x[0-9a-f]{16}$/i.test(d.ieee_address));

  useEffect(() => {
    let active = true;
    getZigbeeMaintenance().then((data) => { if (active) setCapabilities(data); })
      .catch((problem) => { if (active) setError(String(problem?.message || problem)); });
    return () => { active = false; };
  }, []);

  async function pair(seconds) {
    if (busy || !online || !capabilities?.enabled) return;
    if (!window.confirm(t(seconds === 60 ? "devices.zigbee.pairConfirm" : "devices.zigbee.stopConfirm", { gateway: gatewayId }))) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await setZigbeePairing(gatewayId, seconds);
      setNotice(t(seconds === 60 ? "devices.zigbee.pairAcknowledged" : "devices.zigbee.stopAcknowledged"));
      await onRefresh();
    } catch (problem) {
      setError(String(problem?.message || problem));
    } finally { setBusy(false); }
  }

  async function submitSetting(event) {
    event.preventDefault();
    if (busy || !online || !capabilities?.enabled || !capabilities?.settings_enabled ||
        !sensors.some((s) => s.ieee_address === ieee) || !CALIBRATIONS.includes(key) || value.trim() === "") return;
    const number = Number(value);
    if (!Number.isFinite(number) || number < -50 || number > 50) {
      setError(t("devices.zigbee.calibrationInvalid")); return;
    }
    if (!window.confirm(t("devices.zigbee.calibrationConfirm", { ieee }))) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await setZigbeeDeviceOption(gatewayId, ieee, key, number);
      setNotice(t("devices.zigbee.calibrationAcknowledged"));
      await onRefresh();
    } catch (problem) { setError(String(problem?.message || problem)); }
    finally { setBusy(false); }
  }

  return (
    <div className="panel" aria-label={t("devices.zigbee.maintenanceTitle")}>
      <h4>{t("devices.zigbee.maintenanceTitle")}</h4>
      <p className="device-note">{t("devices.zigbee.maintenanceWarning")}</p>
      {error && <p className="device-note" role="alert">{t("devices.zigbee.maintenanceError", { reason: error })}</p>}
      {notice && <p className="device-note" role="status">{notice}</p>}
      {!capabilities?.enabled && <p className="device-note">{t("devices.zigbee.maintenanceDisabled")}</p>}
      <div className="devices-actions">
        <button className="btn btn-secondary" type="button" disabled={busy || !online || !capabilities?.enabled}
          onClick={() => pair(60)}>{t("devices.zigbee.openPairing")}</button>
        <button className="btn btn-secondary" type="button" disabled={busy || !online || !capabilities?.enabled}
          onClick={() => pair(0)}>{t("devices.zigbee.closePairing")}</button>
      </div>
      <p className="device-note">{t("devices.zigbee.pairingInfo")}</p>
      <h4>{t("devices.zigbee.calibrationTitle")}</h4>
      {!capabilities?.settings_enabled && <p className="device-note">{t("devices.zigbee.calibrationDisabled")}</p>}
      <form onSubmit={submitSetting}>
        <div className="device-grid">
          <label className="device-field"><span>{t("devices.zigbee.ieee")}</span>
            <select value={ieee} required onChange={(event) => setIeee(event.target.value)}>
              <option value="">{t("devices.zigbee.chooseSensor")}</option>
              {sensors.map((sensor) => <option key={sensor.ieee_address} value={sensor.ieee_address}>
                {sensor.friendly_name} ({sensor.ieee_address})
              </option>)}
            </select></label>
          <label className="device-field"><span>{t("devices.zigbee.setting")}</span>
            <select value={key} onChange={(event) => setKey(event.target.value)}>
              {CALIBRATIONS.map((option) => <option key={option} value={option}>
                {t(`devices.zigbee.setting.${option}`)}
              </option>)}
            </select></label>
          <label className="device-field"><span>{t("devices.zigbee.calibrationValue")}</span>
            <input type="number" min="-50" max="50" step="0.1" required value={value}
              onChange={(event) => setValue(event.target.value)} /></label>
        </div>
        <button className="btn btn-secondary" type="submit"
          disabled={busy || !online || !capabilities?.enabled || !capabilities?.settings_enabled || !sensors.length || !ieee}>
          {t("devices.zigbee.applyCalibration")}
        </button>
      </form>
    </div>
  );
}
