export default function BatteryIcon({ value, threshold = 20 }) {
  const known = Number.isFinite(value) && value >= 0 && value <= 100;
  const segments = known ? Math.ceil(value / 20) : 0;
  const color = !known ? "#888" : value <= threshold ? "#dc2626" : "currentColor";
  const title = known ? `${value}%` : "—";
  return (
    <span title={title} aria-label={`Battery / 電池 ${title}`} style={{display:"inline-flex",alignItems:"center",color}}>
      <svg width="36" height="18" viewBox="0 0 36 18" fill="none" aria-hidden="true">
        <rect x="1" y="3" width="31" height="12" rx="2" stroke="currentColor"/>
        <path d="M33 7h2v4h-2z" fill="currentColor"/>
        {Array.from({length:5}, (_, i) => (
          <rect key={i} x={3 + i*5.6} y="5" width="4.5" height="8" rx="0.5"
            fill={i < segments ? "currentColor" : "none"} stroke="currentColor" strokeOpacity={0.35}/>
        ))}
      </svg>
    </span>
  );
}
