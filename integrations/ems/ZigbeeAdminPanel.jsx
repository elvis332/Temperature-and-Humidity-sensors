import React, { useCallback, useEffect, useState } from "react";

/** Sander EMS -> Devices -> Zigbee. Mount only behind the current EMS admin role.
 * Credentials and native Zigbee2MQTT ports are never exposed to the browser.
 */
export default function ZigbeeAdminPanel({ basePath="/api/admin/zigbee", csrfToken }) {
  const [gateways, setGateways] = useState([]);
  const [gatewayId, setGatewayId] = useState("");
  const [devices, setDevices] = useState([]);
  const [selection, setSelection] = useState("");
  const [advanced, setAdvanced] = useState(null);
  const [capabilities, setCapabilities] = useState({});
  const [deviceId, setDeviceId] = useState("");
  const [location, setLocation] = useState("");
  const [joinSeconds, setJoinSeconds] = useState(60);
  const [setting, setSetting] = useState("comfort_temperature_max");
  const [settingValue, setSettingValue] = useState("27");
  const [networkIp, setNetworkIp] = useState("");
  const [dhcp, setDhcp] = useState(false);
  const [subnetMask, setSubnetMask] = useState("255.255.255.0");
  const [routerIp, setRouterIp] = useState("");
  const [dnsIp, setDnsIp] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [registration, setRegistration] = useState(null);

  const call = useCallback(async (path, options={}) => {
    const res = await fetch(basePath + path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}), ...(options.headers || {}) },
      ...options,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "EMS API " + res.status);
    return body;
  }, [basePath, csrfToken]);

  const refresh = useCallback(async () => {
    try {
      const [gws, caps] = await Promise.all([call("/gateways"), call("/capabilities")]);
      setGateways(gws);
      setCapabilities(caps);
      setGatewayId(previous => gws.some(g => g.gateway_id === previous)
        ? previous : (gws[0]?.gateway_id || ""));
    } catch (err) { setNotice("EMS Zigbee API unavailable: " + err.message); }
  }, [call]);

  const refreshDevices = useCallback(async () => {
    if (!gatewayId) return;
    try {
      const name = encodeURIComponent(gatewayId);
      const [items, info] = await Promise.all([
        call("/gateways/" + name + "/devices"),
        call("/gateways/" + name + "/advanced"),
      ]);
      setDevices(items);
      setAdvanced(info);
      setSelection(previous => items.some(x => x.ieee_address === previous)
        ? previous : (items[0]?.ieee_address || ""));
    } catch (err) { setNotice("Device discovery unavailable: " + err.message); }
  }, [call, gatewayId]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { refreshDevices(); }, [refreshDevices]);

  const gateway = gateways.find(g => g.gateway_id === gatewayId);
  const selected = devices.find(d => d.ieee_address === selection);
  const gatepath = "/gateways/" + encodeURIComponent(gatewayId);
  const offline = !gateway?.mqtt_connected || gateway?.zigbee2mqtt_state !== "online";
  const settings = ["comfort_temperature_min", "comfort_temperature_max",
    "comfort_humidity_min", "comfort_humidity_max", "temperature_calibration",
    "humidity_calibration"];

  async function perform(label, path, payload) {
    if (loading) return;
    setLoading(true);
    setNotice("");
    try {
      const result = await call(path, { method:"POST", body:JSON.stringify(payload) });
      if (label === "registration") {
        setRegistration(result);
        setNotice("Registration proposal generated; nothing imported into SQL.");
      } else if (label === "setting") {
        setNotice(result.applied === false
          ? "Command sent, not verified on sleeping battery sensor. Wake it and confirm new telemetry."
          : "Zigbee2MQTT acknowledged.");
      } else if (label === "network") {
        setNotice("Network change drafted for IT review. Live coordinator address was not changed.");
      } else {
        setNotice(label + " acknowledged by Zigbee2MQTT.");
      }
      await refresh();
      await refreshDevices();
    } catch (err) { setNotice("Operation failed: " + err.message); }
    finally { setLoading(false); }
  }

  return <section aria-label="Zigbee administrator management" className="ems-zigbee-admin">
    <h2>Zigbee Gateways / Zigbee 閘道器</h2>
    <p>Central administrator management for paired sensors and gateways.</p>
    <label>Gateway
      <select value={gatewayId} onChange={e => { setGatewayId(e.target.value); setRegistration(null); }}>
        {gateways.map(g => <option key={g.gateway_id} value={g.gateway_id}>{g.gateway_id}</option>)}
      </select>
    </label>
    <button type="button" disabled={loading} onClick={refresh}>Refresh gateway status</button>
    <button type="button" disabled={loading || !gatewayId} onClick={refreshDevices}>Discover devices</button>
    {gateway && <p role="status">Gateway {gateway.gateway_id} · {gateway.coordinator_host}:{gateway.coordinator_port}
      · MQTT {gateway.mqtt_connected ? "Connected" : "Offline"}
      · Zigbee2MQTT {gateway.zigbee2mqtt_state} · {gateway.device_count} discovered</p>}
    {notice && <p role="alert">{notice}</p>}

    <fieldset disabled={loading || !gatewayId}>
      <legend>Add sensor / 新增感測器</legend>
      <label>Pairing window in seconds (1–60)
        <input type="number" min="1" max="60" value={joinSeconds}
          onChange={e => setJoinSeconds(Number(e.target.value))}/>
      </label>
      <button type="button" disabled={offline || !Number.isInteger(joinSeconds) || joinSeconds < 1 || joinSeconds > 60}
        onClick={() => perform("pairing", gatepath + "/permit-join", {seconds:joinSeconds})}>
        Open pairing window
      </button>
      <button type="button" disabled={offline}
        onClick={() => perform("close pairing", gatepath + "/permit-join", {seconds:0})}>
        Close pairing
      </button>
      <p>Physical SNZB-02D pairing button is still needed for first enrollment.</p>
      <label>Discovered sensor
        <select value={selection} onChange={e => { setSelection(e.target.value); setRegistration(null); }}>
          {devices.map(d => <option key={d.ieee_address} value={d.ieee_address}>
            {d.friendly_name} ({d.definition?.model || d.model_id}) — {d.ieee_address}
          </option>)}
        </select>
      </label>
      <label>EMS device ID
        <input placeholder="TH-11" value={deviceId} onChange={e => setDeviceId(e.target.value)}/>
      </label>
      <label>Floor / location
        <input placeholder="2F SMT north" value={location} onChange={e => setLocation(e.target.value)}/>
      </label>
      <button type="button" disabled={!selection || !deviceId.trim() || !location.trim()}
        onClick={() => perform("registration", "/registration/plan", {
          gateway_id:gatewayId, ieee_address:selection, device_id:deviceId.trim(),
          location:location.trim(),
        })}>Prepare EMS registration</button>
      {registration && <div>
        <p>Proposed {registration.sensor.device_id}, Modbus Unit {registration.sensor.unit_id}.</p>
        <p>{registration.warning}</p>
        {capabilities.registration_commit_enabled ? (
          <button type="button" onClick={() => perform("EMS commit", "/registration/commit", {
            gateway_id:gatewayId, ieee_address:selection, device_id:deviceId.trim(),
            location:location.trim(),
          })}>Register via approved EMS adapter</button>
        ) : <p>Database commit disabled until the existing EMS Devices adapter is installed and approved.</p>}
      </div>}
    </fieldset>

    <fieldset disabled={loading || !gatewayId}>
      <legend>Advanced Maintenance / 進階維護</legend>
      <label>Sensor
        <select value={selection} onChange={e => setSelection(e.target.value)}>
          {devices.map(d => <option key={d.ieee_address} value={d.ieee_address}>
            {d.friendly_name} — {d.ieee_address}
          </option>)}
        </select>
      </label>
      <label>Setting
        <select value={setting} onChange={e => setSetting(e.target.value)}>
          {settings.map(x => <option key={x} value={x}>{x}</option>)}
        </select>
      </label>
      <label>Value
        <input type="number" step="0.1" value={settingValue} onChange={e => setSettingValue(e.target.value)}/>
      </label>
      <button type="button" disabled={offline || !selected || settingValue.trim() === ""}
        onClick={() => perform("setting", gatepath + "/devices/" + encodeURIComponent(selection) + "/expose",
          {setting, value:Number(settingValue)})}>Send setting</button>
      <p>Settings sent to sleeping sensors are not proof of application. Wake sensor and verify its new report.</p>
      {advanced?.configured ? <a href={advanced.native_admin_path} rel="noopener noreferrer" target="_blank">
        Open native Zigbee2MQTT administrator dashboard
      </a> : <p>Native dashboard remains disabled until Valen configures an authenticated server reverse proxy.</p>}
    </fieldset>

    <fieldset disabled={loading || !gatewayId}>
      <legend>Gateway Network / 閘道器網路</legend>
      <label>Proposed coordinator IP (review only)
        <input value={networkIp} placeholder="192.168.x.x" onChange={e => setNetworkIp(e.target.value)}/>
      </label>
      <label>
        <input type="checkbox" checked={dhcp} onChange={e => setDhcp(e.target.checked)}/>
        DHCP enabled / DHCP
      </label>
      <label>Subnet mask
        <input value={subnetMask} onChange={e => setSubnetMask(e.target.value)}
          disabled={dhcp} placeholder="255.255.255.0"/>
      </label>
      <label>Router / Gateway IP
        <input value={routerIp} onChange={e => setRouterIp(e.target.value)}
          disabled={dhcp} placeholder="192.168.x.1"/>
      </label>
      <label>Company-approved DNS
        <input value={dnsIp} onChange={e => setDnsIp(e.target.value)}
          disabled={dhcp} placeholder="192.168.x.x"/>
      </label>
      <button type="button" disabled={!networkIp.trim()}
        onClick={() => perform("network", gatepath + "/network/propose", {
          coordinator_host:networkIp.trim(), coordinator_port:6638,
          coordinator_transport:"ethernet_tcp",
          dhcp, subnet_mask:dhcp ? null : subnetMask,
          default_gateway:dhcp ? null : (routerIp.trim() || null),
          dns_servers:dhcp || !dnsIp.trim() ? [] : [dnsIp.trim()],
        })}>Request IT network review</button>
      <p>No live SLZB-06MU IP or Zigbee2MQTT configuration is changed by this form.</p>
    </fieldset>
  </section>;
}
