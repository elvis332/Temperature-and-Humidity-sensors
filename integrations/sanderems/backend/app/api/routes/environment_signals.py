"""Additive EMS endpoint for out-of-range, offline and sudden-change notices."""
import json
from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.api.dependencies import get_db
from backend.app.api.routes.environment import _overview
from backend.app.core.timeutil import now_local
from backend.app.database.models import DeviceSettings, TelemetryEvent, TelemetryReading

router = APIRouter(prefix='/environment', tags=['Environment'])

@router.get('/signals')
def environment_signals(db: Session = Depends(get_db)):
    overview = _overview(db)
    notices = []
    for sensor in overview['sensors']:
        sid = sensor['id']
        if sensor['status'] in ('offline', 'data_error', 'no_data'):
            notices.append({'device_id': sid, 'code': sensor['status'], 'severity': 'warning'})
        for key in sensor.get('alarms', []):
            notices.append({'device_id': sid, 'code': f'{key}_limit', 'severity': 'alarm'})
        if sensor['status'] not in ('normal', 'data_error'):
            continue
        row = db.get(DeviceSettings, sid)
        settings = json.loads(row.settings_json) if row else {}
        limits = settings.get('zigbee_alerts', {})
        minutes = int(limits.get('jump_minutes', 10))
        for key, option, default in (
            ('temperature_c', 'temperature_jump', 2),
            ('humidity_pct', 'humidity_jump', 10),
        ):
            points = db.execute(
                select(TelemetryEvent.measured_at, TelemetryReading.value_numeric)
                .join(TelemetryReading, TelemetryReading.event_id == TelemetryEvent.id)
                .where(
                    TelemetryEvent.device_id == sid,
                    TelemetryEvent.measured_at >= now_local() - timedelta(minutes=minutes),
                    TelemetryReading.point_key == key,
                    TelemetryReading.quality == 'GOOD',
                )
                .order_by(TelemetryEvent.measured_at.desc()).limit(2)
            ).all()
            if len(points) == 2 and all(p.value_numeric is not None for p in points):
                delta = abs(float(points[0].value_numeric) - float(points[1].value_numeric))
                if delta >= float(limits.get(option, default)):
                    notices.append({'device_id': sid, 'code': f'{key}_jump',
                                    'severity': 'warning', 'difference': round(delta, 2)})
    return {'generated_at': overview['generated_at'], 'signals': notices}
