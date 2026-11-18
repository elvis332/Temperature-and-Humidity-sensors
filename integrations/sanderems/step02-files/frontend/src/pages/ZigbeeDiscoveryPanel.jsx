import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { getZigbeeDiscovery } from "../api";
import { useI18n } from "../i18n";

// Read-only inventory for the existing Devices page; server controls availability.
export default function ZigbeeDiscoveryPanel() {
  const { t } = useI18n();
  const [snapshot, setSnapshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setSnapshot(await getZigbeeDiscovery());
    } catch (problem) {
      setSnapshot(null);
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="devices-zigbee-discovery">
      <div className="devices-actions">
        <button className="btn btn-secondary" type="button" onClick={refresh} disabled={busy}>
          <RefreshCw size={16} /> {t("devices.zigbee.refresh")}
        </button>
      </div>
      {busy && <p className="device-note" role="status">{t("devices.zigbee.loading")}</p>}
      {error && <p className="device-note" role="alert">{t("devices.zigbee.error", { reason: error })}</p>}
      {snapshot && !snapshot.enabled && <p className="device-note">{t("devices.zigbee.disabled")}</p>}
      {snapshot?.enabled && snapshot.gateways.length === 0 &&
        <p className="device-note">{t("devices.zigbee.noGateways")}</p>}
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
                </tr></thead>
                <tbody>{gateway.devices.map((sensor) => (
                  <tr key={sensor.ieee_address}>
                    <td>{sensor.friendly_name || "—"}</td>
                    <td>{sensor.model || "—"}</td>
                    <td>{sensor.ieee_address}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      ))}
      <p className="device-note">{t("devices.zigbee.snapshotNote")}</p>
    </div>
  );
}
