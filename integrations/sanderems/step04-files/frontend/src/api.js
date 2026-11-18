const SETTINGS_KEY = "sander_ems_server_settings";

const DEFAULT_SETTINGS = {
  protocol: "http",
  host: "127.0.0.1",
  port: "8000",
};

function normalizeHost(host) {
  return String(host || "")
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/\/+$/, "");
}

function normalizePort(port) {
  return String(port || "").trim();
}

export function getServerSettings() {
  try {
    const saved = window.localStorage.getItem(SETTINGS_KEY);

    if (saved) {
      const parsed = JSON.parse(saved);

      return {
        protocol:
          parsed.protocol === "https"
            ? "https"
            : "http",
        host:
          normalizeHost(parsed.host) ||
          DEFAULT_SETTINGS.host,
        port:
          normalizePort(parsed.port) ||
          DEFAULT_SETTINGS.port,
      };
    }
  } catch (error) {
    console.warn(
      "Could not read saved EMS server settings:",
      error
    );
  }

  return { ...DEFAULT_SETTINGS };
}

export function saveServerSettings(settings) {
  const clean = {
    protocol:
      settings.protocol === "https"
        ? "https"
        : "http",
    host:
      normalizeHost(settings.host) ||
      DEFAULT_SETTINGS.host,
    port:
      normalizePort(settings.port) ||
      DEFAULT_SETTINGS.port,
  };

  window.localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify(clean)
  );

  return clean;
}

export function resetServerSettings() {
  window.localStorage.removeItem(SETTINGS_KEY);
}

export function buildApiBase(settings) {
  const clean = settings || getServerSettings();

  const protocol =
    clean.protocol === "https"
      ? "https"
      : "http";

  const host =
    normalizeHost(clean.host) ||
    DEFAULT_SETTINGS.host;

  const port =
    normalizePort(clean.port);

  const portPart =
    port ? `:${port}` : "";

  return `${protocol}://${host}${portPart}/api`;
}

function getApiBase() {
  /*
   * The dashboard is served by scripts/serve_frontend.py, which
   * forwards /api to the FastAPI service. A same-origin relative
   * path therefore works from every machine.
   *
   * A server address saved in this browser by the old per-user
   * setting is ignored on purpose, so stale entries cannot point
   * the dashboard at the wrong machine.
   */
  return (
    import.meta.env.VITE_API_BASE_URL ||
    "/api"
  );
}

async function readError(response, fallback) {
  try {
    const payload = await response.json();

    // FastAPI validation errors (422) carry a list of field problems.
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) => `${(item.loc || []).slice(1).join(".")}: ${item.msg}`)
        .join("; ");
    }

    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function apiGet(path) {
  const response = await fetch(
    `${getApiBase()}${path}`
  );

  if (!response.ok) {
    const message = await readError(
      response,
      `API request failed: ${response.status}`
    );

    throw new Error(message);
  }

  return response.json();
}

export async function testServerConnection(settings) {
  const apiBase = buildApiBase(settings);

  const controller =
    new AbortController();

  const timeout =
    window.setTimeout(
      () => controller.abort(),
      5000
    );

  const started =
    performance.now();

  try {
    const response = await fetch(
      `${apiBase}/health`,
      {
        method: "GET",
        signal: controller.signal,
      }
    );

    if (!response.ok) {
      const message = await readError(
        response,
        `Server returned HTTP ${response.status}`
      );

      throw new Error(message);
    }

    const payload = await response.json();

    const latencyMs =
      Math.round(
        performance.now() - started
      );

    return {
      ok: true,
      apiBase,
      latencyMs,
      payload,
    };
  } finally {
    window.clearTimeout(timeout);
  }
}

async function apiPost(path, body, method = "POST") {
  const response = await fetch(
    `${getApiBase()}${path}`,
    {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body ?? {}),
    }
  );

  if (!response.ok) {
    const message = await readError(
      response,
      `API request failed: ${response.status}`
    );

    throw new Error(message);
  }

  return response.json();
}

/*
 * Sign-in uses an HttpOnly session cookie set by the API.
 * The dashboard and /api share one origin, so fetch sends the
 * cookie without any extra option.
 */
export async function getCurrentUser() {
  const response = await fetch(
    `${getApiBase()}/auth/me`
  );

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      await readError(
        response,
        `API request failed: ${response.status}`
      )
    );
  }

  return response.json();
}

export function login(username, password) {
  return apiPost("/auth/login", {
    username,
    password,
  });
}

export function logout() {
  return apiPost("/auth/logout");
}

// Device administration. Every call needs an administrator session.
export function getAdminProfiles() {
  return apiGet("/admin/profiles");
}

export function getAdminDevices() {
  return apiGet("/admin/devices");
}

export function getAdminDevice(deviceId) {
  return apiGet(`/admin/devices/${encodeURIComponent(deviceId)}`);
}

export function getAdminDeviceHistory(deviceId) {
  return apiGet(`/admin/devices/${encodeURIComponent(deviceId)}/history`);
}

export function createAdminDevice(form) {
  return apiPost("/admin/devices", form);
}

// The "Collect" switch on the device list.
export function setDeviceCollection(deviceId, enabled, expectedUpdatedAt) {
  return apiPost(
    `/admin/devices/${encodeURIComponent(deviceId)}/collection`,
    { enabled, expected_updated_at: expectedUpdatedAt },
    "PUT",
  );
}

export function updateAdminDevice(deviceId, form) {
  return apiPost(`/admin/devices/${encodeURIComponent(deviceId)}`, form, "PUT");
}

// Service status and control (System page). Administrator only.
export function getSystemServices() {
  return apiGet("/admin/system/services");
}

export function getServiceActions(limit = 20) {
  return apiGet(`/admin/system/actions?limit=${limit}`);
}

// Service actions and device setting changes, newest first.
export function getActivity(limit = 100) {
  return apiGet(`/admin/system/activity?limit=${limit}`);
}

// Events received / expected and their quality, per device.
export function getDataQuality(hours = 24) {
  return apiGet(`/admin/system/data-quality?hours=${hours}`);
}

export function controlService(serviceId, action) {
  return apiPost(
    `/admin/system/services/${encodeURIComponent(serviceId)}/${encodeURIComponent(action)}`
  );
}

// Account management (System page). Administrator only.
export function getUsers() {
  return apiGet("/admin/users");
}

export function createUser(username, password) {
  return apiPost("/admin/users", { username, password });
}

export function setUserPassword(userId, password) {
  return apiPost(`/admin/users/${userId}/password`, { password }, "PUT");
}

export function setUserActive(userId, isActive) {
  return apiPost(`/admin/users/${userId}/active`, { is_active: isActive }, "PUT");
}


// Environmental monitoring. Public, read-only endpoints.
export function getEnvironmentOverview() {
  return apiGet("/environment/overview");
}

export function getEnvironmentSensors() {
  return apiGet("/environment/sensors");
}

export function getEnvironmentSensor(deviceId, hours = 24, limit = 500) {
  const query = new URLSearchParams({
    hours: String(hours),
    limit: String(limit),
  });

  return apiGet(
    `/environment/sensors/${encodeURIComponent(deviceId)}?${query.toString()}`
  );
}

export function getHealth() {
  return apiGet("/health");
}

export function getSite() {
  return apiGet("/site");
}

export function getDevices() {
  return apiGet("/devices");
}

// Every energy meter and the factory total in one call (Power page).
export function getPowerOverview() {
  return apiGet("/power/overview");
}

export function getDevice(deviceId) {
  return apiGet(
    `/devices/${encodeURIComponent(deviceId)}`
  );
}

export function getLatest(deviceId) {
  return apiGet(
    `/devices/${encodeURIComponent(deviceId)}/latest`
  );
}

export function getHistory(
  deviceId,
  limit = 60
) {
  return apiGet(
    `/devices/${encodeURIComponent(deviceId)}/history?limit=${limit}`
  );
}

export function getSummaries(
  deviceId,
  interval,
  limit = 24
) {
  const query =
    new URLSearchParams({
      interval,
      limit: String(limit),
    });

  return apiGet(
    `/devices/${encodeURIComponent(deviceId)}/summaries?${query.toString()}`
  );
}

function defaultDownloadName({
  scope,
  startDate,
  endDate,
  interval,
  format,
  data = "power",
}) {
  const safeScope =
    scope === "ALL"
      ? (data === "power" ? "All_Factory" : "All_TempHumidity")
      : scope.replace(
          /[^A-Za-z0-9_-]+/g,
          "_"
        );

  return (
    `Factory_EMS_${safeScope}_` +
    `${startDate}_to_${endDate}_` +
    `${interval}.${format}`
  );
}

// Row count and Excel sheets of an export, shown before download.
export function getReportPreview({ scope, startDate, endDate, interval, data = "power" }) {
  const query = new URLSearchParams({
    scope,
    start_date: startDate,
    end_date: endDate,
    interval,
    data,
  });

  return apiGet(`/reports/preview?${query.toString()}`);
}

export async function downloadReport({
  scope,
  startDate,
  endDate,
  interval,
  format,
  data = "power",
}) {
  const query =
    new URLSearchParams({
      scope,
      start_date: startDate,
      end_date: endDate,
      interval,
      format,
      data,
    });

  const response =
    await fetch(
      `${getApiBase()}/reports/export?${query.toString()}`
    );

  if (!response.ok) {
    const message = await readError(
      response,
      `Report export failed: ${response.status}`
    );

    throw new Error(message);
  }

  const blob =
    await response.blob();

  const filename =
    defaultDownloadName({
      scope,
      startDate,
      endDate,
      interval,
      format,
      data,
    });

  const url =
    window.URL.createObjectURL(
      blob
    );

  const anchor =
    document.createElement("a");

  anchor.href = url;
  anchor.download = filename;

  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  window.URL.revokeObjectURL(url);

  return filename;
}

// Read-only admin gateway discovery; same EMS API/authentication as other Devices data.
export function getZigbeeDiscovery() {
  return apiGet("/admin/zigbee/discovery");
}


export function getZigbeeMaintenance() {
  return apiGet("/admin/zigbee/maintenance");
}

export function setZigbeePairing(gatewayId, seconds) {
  return apiPost(`/admin/zigbee/gateways/${encodeURIComponent(gatewayId)}/pair`, {
    seconds,
    confirmation: gatewayId,
  });
}

export function setZigbeeDeviceOption(gatewayId, ieeeAddress, key, value) {
  return apiPost(`/admin/zigbee/gateways/${encodeURIComponent(gatewayId)}/device-options`, {
    ieee_address: ieeeAddress,
    key,
    value,
    confirmation: ieeeAddress,
  });
}
