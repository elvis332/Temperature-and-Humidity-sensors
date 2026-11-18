import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { createAdminDevice, getAdminDevices, getAdminProfiles, getZigbeeDiscovery } from "../api";
import { useI18n } from "../i18n";

const SUPPORTED_MODEL = "SNZB-02D";
const IEEE_PATTERN = /^0x[0-9a-f]{16}$/i;

// Keep the physical IEEE identity stable even when a sensor moves between gateways.
function sensorId(ieee) {
  return IEEE_PATTERN.test(ieee || "") ? `ZB_${ieee.slice(2).toUpperCase()}` : null;
}

function isValidIPv4(value) {
  const parts = value.split(".");
  return parts.length === 4 && parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255);
}

function newDraft(gatewayId, sensor) {
  return {
    gatewayId,
    ieee: sensor.ieee_address,
    deviceId: sensorId(sensor.ieee_address),
    name: (sensor.friendly_name || "SNZB-02D").slice(0, 255),
    building: "",
    floor: "",
    location: "",
    ip: "",
    port: "",
    unit: "",
    confirmed: false,
  };
}

// Registration reuses Valen's existing administrator-only Devices API and audit history.
// There is no Zigbee write, new database table or automatic collection here.
export default function ZigbeeDiscoveryPanel() {
  const { t } = useI18n();
  const [snapshot, setSnapshot] = useState(null);
  const [registered, setRegistered] = useState([]);
  const [hasProfile, setHasProfile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [inventory, devices, profiles] = await Promise.all([
        getZigbeeDiscovery(), getAdminDevices(), getAdminProfiles(),
      ]);
      setSnapshot(inventory);
      setRegistered(devices);
      setHasProfile(profiles.some((p) => p.id === "SNZB02D"));
    } catch (problem) {
      setSnapshot(null);
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function change(field, value) {
    setDraft((current) => current ? { ...current, [field]: value } : current);
  }

  async function register(event) {
    event.preventDefault();
    if (!draft || saving || !hasProfile) return;
    setError("");
    setNotice("");
    const id = sensorId(draft.ieee);
    if (!id || id !== draft.deviceId || !draft.confirmed || !draft.floor.trim() ||
        !draft.location.trim() || !draft.name.trim() || !isValidIPv4(draft.ip.trim()) ||
        !Number.isInteger(Number(draft.port)) || Number(draft.port) < 1 || Number(draft.port) > 65535 ||
        !Number.isInteger(Number(draft.unit)) || Number(draft.unit) < 1 || Number(draft.unit) > 247) {
      setError(t("devices.zigbee.registrationInvalid"));
      return;
    }
    setSaving(true);
    try {
      // Recheck on submission: a second administrator may have registered in the meantime.
      const latest = await getAdminDevices();
      if (latest.some((d) => d.device_id.toUpperCase() === id.toUpperCase())) {
        throw new Error(t("devices.zigbee.alreadyRegistered"));
      }
      if (latest.some((d) => d.ip_address === draft.ip.trim() &&
          Number(d.port) === Number(draft.port) && Number(d.modbus_unit_id) === Number(draft.unit))) {
        throw new Error(t("devices.zigbee.endpointTaken"));
      }
      await createAdminDevice({
        device_id: id,
        profile_id: "SNZB02D",
        display_name: draft.name.trim(),
        description: `Zigbee2MQTT gateway ${draft.gatewayId}; IEEE ${draft.ieee.toLowerCase()}`,
        status: "commissioning",
        parent_panel: null,
        role: "to_confirm",
        parent_meter_id: null,
        location: {
          building: draft.building.trim() || null,
          floor: draft.floor.trim(),
          electrical_panel: null,
          system_group: draft.location.trim(),
        },
        electrical: { ct_primary_a: null, ct_secondary_a: null, pt_primary_v: null, pt_secondary_v: null },
        communication: {
          ip_address: draft.ip.trim(),
          port: Number(draft.port),
          modbus_unit_id: Number(draft.unit),
        },
        collection: { enabled: false, sampling_seconds: 60, timeout_seconds: 5, retry_count: 3 },
        points: {},
      });
      setDraft(null);
      setRegistered(await getAdminDevices());
      setNotice(t("devices.zigbee.registrationSaved", { id }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="devices-zigbee-discovery">
      <div className="devices-actions">
        <button className="btn btn-secondary" type="button" onClick={refresh} disabled={busy || saving}>
          <RefreshCw size={16} /> {t("devices.zigbee.refresh")}
        </button>
      </div>
      {busy && <p className="device-note" role="status">{t("devices.zigbee.loading")}</p>}
      {error && <p className="device-note" role="alert">{t("devices.zigbee.error", { reason: error })}</p>}
      {notice && <p className="device-note" role="status">{notice}</p>}
      {snapshot && !snapshot.enabled && <p className="device-note">{t("devices.zigbee.disabled")}</p>}
      {snapshot?.enabled && snapshot.gateways.length === 0 &&
        <p className="device-note">{t("devices.zigbee.noGateways")}</p>}
      {snapshot?.enabled && !hasProfile &&
        <p className="device-note" role="alert">{t("devices.zigbee.profileMissing")}</p>}
      {snapshot?.enabled && snapshot.gateways.map((gateway) => (
        <section key={gateway.gateway_id} className="panel" aria-label={gateway.gateway_id}>
          <h4>{gateway.gateway_id}</h4>
          <p className="device-note">
            {gateway.mqtt_connected ? t("devices.zigbee.connected") : t("devices.zigbee.disconnected")}
            {" · "}{t("devices.zigbee.state")}: {gateway.zigbee2mqtt_state}
            {" · "}{t("devices.zigbee.sensors")}: {gateway.devices.length}
          </p>
          {gateway.devices.length === 0 ? (
            <p className="device-note">{t("devices.zigbee.none")}</p>
          ) : (
            <div className="devices-table-wrap">
              <table className="devices-table">
                <thead><tr>
                  <th>{t("devices.col.id")}</th>
                  <th>{t("devices.zigbee.model")}</th>
                  <th>{t("devices.zigbee.ieee")}</th>
                  <th>{t("devices.zigbee.action")}</th>
                </tr></thead>
                <tbody>{gateway.devices.map((sensor) => {
                  const id = sensorId(sensor.ieee_address);
                  const known = id && registered.some((d) => d.device_id.toUpperCase() === id.toUpperCase());
                  const supported = sensor.model === SUPPORTED_MODEL && Boolean(id);
                  return (
                    <tr key={sensor.ieee_address}>
                      <td>{sensor.friendly_name || "—"}</td>
                      <td>{sensor.model || "—"}</td>
                      <td>{sensor.ieee_address}</td>
                      <td>{known ? t("devices.zigbee.registered") : supported ? (
                        <button className="btn btn-secondary" type="button"
                          disabled={!hasProfile || busy || saving || !gateway.mqtt_connected || gateway.zigbee2mqtt_state !== "online"}
                          onClick={() => { setDraft(newDraft(gateway.gateway_id, sensor)); setError(""); setNotice(""); }}>
                          {t("devices.zigbee.register")}
                        </button>
                      ) : t("devices.zigbee.unsupported")}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          )}
          {draft?.gatewayId === gateway.gateway_id && (
            <form onSubmit={register} className="panel">
              <h4>{t("devices.zigbee.registrationTitle")}</h4>
              <p className="device-note">{t("devices.zigbee.registrationNotice")}</p>
              <div className="device-grid">
                <label className="device-field"><span>{t("devices.field.deviceId")}</span>
                  <input value={draft.deviceId} readOnly /></label>
                <label className="device-field"><span>{t("devices.field.name")}</span>
                  <input value={draft.name} maxLength={255} required onChange={(e) => change("name", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.field.building")}</span>
                  <input value={draft.building} maxLength={100} onChange={(e) => change("building", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.field.floor")}</span>
                  <input value={draft.floor} maxLength={100} required onChange={(e) => change("floor", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.zigbee.location")}</span>
                  <input value={draft.location} maxLength={100} required onChange={(e) => change("location", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.zigbee.bridgeIp")}</span>
                  <input value={draft.ip} required placeholder="192.168.x.x" onChange={(e) => change("ip", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.zigbee.bridgePort")}</span>
                  <input type="number" min="1" max="65535" required value={draft.port} onChange={(e) => change("port", e.target.value)} /></label>
                <label className="device-field"><span>{t("devices.zigbee.bridgeUnit")}</span>
                  <input type="number" min="1" max="247" required value={draft.unit} onChange={(e) => change("unit", e.target.value)} /></label>
              </div>
              <label className="device-field">
                <span><input type="checkbox" checked={draft.confirmed} onChange={(e) => change("confirmed", e.target.checked)} /> {t("devices.zigbee.verifyBridge")}</span>
              </label>
              <div className="devices-actions">
                <button className="btn btn-secondary" type="button" onClick={() => setDraft(null)} disabled={saving}>{t("common.cancel")}</button>
                <button className="btn btn-primary" type="submit" disabled={saving || !draft.confirmed || !hasProfile}>{saving ? t("common.saving") : t("devices.zigbee.saveRegistration")}</button>
              </div>
            </form>
          )}
        </section>
      ))}
      <p className="device-note">{t("devices.zigbee.snapshotNote")}</p>
    </div>
  );
}
