import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useI18n } from "../i18n";

const LABELS = {
  offline: ["No sensor readings", "感測器未回傳資料"],
  no_data: ["Sensor not reporting", "感測器尚未回報"],
  data_error: ["Invalid sensor data", "感測器資料異常"],
  temperature_c_limit: ["Temperature outside limits", "溫度超出設定範圍"],
  humidity_pct_limit: ["Humidity outside limits", "濕度超出設定範圍"],
  temperature_c_jump: ["Sudden temperature change", "溫度突然變化"],
  humidity_pct_jump: ["Sudden humidity change", "濕度突然變化"],
};

export default function EnvironmentSignalStrip() {
  const { language } = useI18n();
  const [signals, setSignals] = useState([]);
  useEffect(() => {
    let active = true;
    const refresh = () => fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/environment/signals`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => { if (active) setSignals(data.signals || []); })
      .catch(() => { if (active) setSignals([]); });
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if (!signals.length) return null;
  const zh = language === "zh";
  return (
    <section className="panel" aria-label={zh ? "環境警示" : "Environment warnings"}>
      <h3><AlertTriangle size={18} /> {zh ? "環境警示" : "Environment warnings"} ({signals.length})</h3>
      {signals.map((signal, i) => (
        <p key={`${signal.device_id}-${signal.code}-${i}`} className="env-card-alarm">
          <AlertTriangle size={14} /> <strong>{signal.device_id}</strong> — {LABELS[signal.code]?.[zh ? 1 : 0] || signal.code}
          {signal.difference != null ? ` (${signal.difference})` : ""}
        </p>
      ))}
    </section>
  );
}
