"""Zigbee2MQTT decoding, local historian, and per-sensor alarms; never writes to actuators."""
import json
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def decode(topic, payload, sensors, mode):
    sensor = next((s for s in sensors if s['topic'] == topic), None)
    if not sensor:
        return None
    obj = json.loads(payload)
    if not isinstance(obj, dict) or bool(obj.get('_simulated')) != (mode == 'simulation'):
        return None
    values = {}
    for key, minimum, maximum in (('temperature', -40, 85), ('humidity', 0, 100), ('battery', 0, 100)):
        v = obj.get(key)
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not minimum <= v <= maximum:
                raise ValueError(f'invalid {key}: {v!r}')
            values[key] = float(v)
    if not {'temperature', 'humidity'} <= values.keys():
        raise ValueError('temperature and humidity are required')
    return sensor, values


def locked(method):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper


class Engine:
    def __init__(self, config):
        self.config = config
        db = Path(config['database'])
        db.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(db, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY, sensor TEXT NOT NULL, received TEXT NOT NULL, mode TEXT NOT NULL, temperature REAL, humidity REAL, battery REAL);
        CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, sensor TEXT NOT NULL, kind TEXT NOT NULL, opened TEXT NOT NULL, closed TEXT, detail TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS readings_by_sensor ON readings(sensor,id);
        CREATE INDEX IF NOT EXISTS active_alerts ON alerts(sensor,kind,closed);
        ''')
        self.started = datetime.now(timezone.utc)

    def _alert(self, sensor, kind, on, detail, now):
        row = self.db.execute('SELECT id FROM alerts WHERE sensor=? AND kind=? AND closed IS NULL', (sensor, kind)).fetchone()
        if on and not row:
            self.db.execute('INSERT INTO alerts(sensor,kind,opened,detail) VALUES(?,?,?,?)', (sensor, kind, now, detail))
        elif not on and row:
            self.db.execute('UPDATE alerts SET closed=? WHERE id=?', (now, row[0]))

    @locked
    def record(self, topic, payload):
        decoded = decode(topic, payload, self.config['sensors'], self.config['mode'])
        if not decoded:
            return False
        sensor, vals = decoded
        sid, now = sensor['id'], utcnow()
        previous = self.db.execute('SELECT received,temperature,humidity FROM readings WHERE sensor=? ORDER BY id DESC LIMIT 1', (sid,)).fetchone()
        self.db.execute('INSERT INTO readings(sensor,received,mode,temperature,humidity,battery) VALUES(?,?,?,?,?,?)',
                        (sid, now, self.config['mode'], vals['temperature'], vals['humidity'], vals.get('battery')))
        for field in ('temperature', 'humidity'):
            value = vals[field]
            self._alert(sid, field+'_low', value < sensor[field+'_min'], f'{value} < {sensor[field+"_min"]}', now)
            self._alert(sid, field+'_high', value > sensor[field+'_max'], f'{value} > {sensor[field+"_max"]}', now)
            jumping = bool(previous and (datetime.fromisoformat(now)-datetime.fromisoformat(previous[0])).total_seconds() <= sensor['jump_minutes']*60 and abs(value-previous[1 if field=='temperature' else 2]) >= sensor[field+'_jump'])
            self._alert(sid, field+'_jump', jumping, f'rapid {field} change to {value}', now)
        self._alert(sid, 'offline', False, 'reconnected', now)
        self.db.commit()
        return True

    @locked
    def check_offline(self):
        now = datetime.now(timezone.utc)
        for sensor in self.config['sensors']:
            row = self.db.execute('SELECT received FROM readings WHERE sensor=? ORDER BY id DESC LIMIT 1',
                                  (sensor['id'],)).fetchone()
            last = datetime.fromisoformat(row[0]) if row else self.started
            self._alert(sensor['id'], 'offline', (now-last).total_seconds() > sensor['offline_seconds'],
                        'no recent MQTT readings', now.isoformat())
        self.db.commit()

    @locked
    def status(self):
        readings = self.db.execute('SELECT sensor,received,mode,temperature,humidity,battery FROM readings WHERE id IN (SELECT MAX(id) FROM readings GROUP BY sensor) ORDER BY sensor').fetchall()
        alerts = self.db.execute('SELECT sensor,kind,opened,detail FROM alerts WHERE closed IS NULL ORDER BY sensor,kind').fetchall()
        return readings, alerts
