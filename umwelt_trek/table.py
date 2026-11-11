#!/usr/bin/env python3
"""Per-minute feature table: the collector's JSONL sessions in, one row per minute out.

    python -m umwelt_trek.table --data DATA_DIR --out OUT_DIR [--episodes episodes.csv] [--labels-map map.json]
                                [--tz Area/City] [--sessions a,b] [--imu-cal f.json] [--mag-cal f.json]

DATA_DIR holds one folder per session; every `data_*.jsonl` under a session folder is read (docs/RECORDS.md).
Each column is the median over the minute of the values `features.py` makes; a few also get the minute's
spread (`_sd`). The first five columns are bookkeeping and never model inputs:

    minute_utc, day_local, session, labels, carrier

`day_local` is the local calendar day (--tz), used only to hold out whole days when scoring. `labels` are the
words of every episode in episodes.csv covering the minute. `carrier` is derived from them with the labels
map: vehicle / bag-at-rest / bag-carried, else `desk` when the minute has no episode and the machine is on
mains power, else empty (unlabelled, dropped by the trainer).

No clock column and no coordinates are written, by design: a scene model must find the scene in the sensors,
not in the time of day or the place. The table is still a dense record of someone's days. Keep it private.
"""
import argparse
import csv
import glob
import json
import os
import statistics as st
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import orient
from .features import Context, record_features

SD_COLS = ('aud_laptop_rms_db', 'aud_usb_rms_db', 'aud_c920_rms_db', 'gps_ub_speed', 'gps_sirf_speed',
           'imu_g_norm', 'imu_rate', 'imu_roll', 'imu_pitch', 'opt_loglux')
WANTED = ('"gps"', '"audio_spectrum"', '"bluetooth"', '"wifi"', '"radiation"', '"spectrum"', '"system"',
          '"usb_monitor"', '"light"', '"hue"', '"imu"', '"optical"')
DEFAULT_LABELS_MAP = {
    'vehicle': ['vehicle', 'bus', 'train', 'car'],
    'bag-at-rest': ['bag-at-rest'],
    'bag-carried': ['bag-carried', 'walk', 'commute'],
    'desk': ['desk', 'night'],
}


def minute_of(rec):
    """Records are binned by the minute their measurement started."""
    raw = rec.get('started') or rec.get('timestamp')
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None
    return int(t.timestamp() // 60)


def load_episodes(path):
    """episodes.csv: start_utc, end_utc, labels (';'-joined), then any columns of your own."""
    eps = []
    if not path:
        return eps
    with open(path) as fh:
        for r in csv.DictReader(fh):
            s = int(datetime.fromisoformat(r['start_utc'].replace('Z', '+00:00')).timestamp() // 60)
            e = int(datetime.fromisoformat(r['end_utc'].replace('Z', '+00:00')).timestamp() // 60) if r['end_utc'] else s + 1
            eps.append((s, e, r['labels'].split(';')))
    return eps


def labels_for(minute, eps):
    out = []
    for s, e, labs in eps:
        if s <= minute < e:
            out.extend(labs)
    return sorted(set(out))


def carrier_of(labels, plugged, lmap):
    L = set(labels)
    if L & set(lmap.get('vehicle', ())):
        return 'vehicle'
    if L & set(lmap.get('bag-at-rest', ())):
        return 'bag-at-rest'
    if L & set(lmap.get('bag-carried', ())):
        return 'bag-carried'
    if not L and plugged == 1:
        return 'desk'
    if L & set(lmap.get('desk', ())) and plugged == 1:
        return 'desk'
    return ''


def session_names(data, wanted=None):
    if wanted:
        return wanted
    return [n for n in sorted(os.listdir(data))
            if os.path.isdir(os.path.join(data, n)) and glob.glob(os.path.join(data, n, '**', 'data_*.jsonl'), recursive=True)]


def build(data, names, eps, lmap, tz, ctx, log=None):
    """-> (header, rows, info). rows are lists of strings, ready for csv."""
    log = log or sys.stderr
    rows, src = {}, {}
    for name in names:
        files = sorted(glob.glob(os.path.join(data, name, '**', 'data_*.jsonl'), recursive=True))
        if not files:
            continue
        ctx.new_session()
        n = 0
        for p in files:
            with open(p) as fh:
                for line in fh:
                    if not any(w in line[:400] for w in WANTED):
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    m = minute_of(rec)
                    if m is None:
                        continue
                    f = record_features(rec, ctx)
                    if not f:
                        continue
                    n += 1
                    cols = rows.setdefault(m, {})
                    src[m] = name
                    for k, v in f.items():
                        cols.setdefault(k, []).append(v)
        print(f'{name}: {len(files)} files, {n} records used', file=log)
    columns = sorted({k for c in rows.values() for k in c})
    sd_cols = [c + '_sd' for c in SD_COLS if c in columns]
    header = ['minute_utc', 'day_local', 'session', 'labels', 'carrier'] + columns + sd_cols
    out, counts = [], {}
    for m in sorted(rows):
        t = datetime.fromtimestamp(m * 60, timezone.utc)
        c = rows[m]
        labs = labels_for(m, eps)
        plugged = round(st.median(c['sys_plugged'])) if 'sys_plugged' in c else None
        car = carrier_of(labs, plugged, lmap)
        counts[car] = counts.get(car, 0) + 1
        vals = [('%.5g' % st.median(c[k])) if k in c else '' for k in columns]
        sds = [('%.4g' % st.pstdev(c[k])) if k in c and len(c[k]) >= 3 else '' for k in SD_COLS if k in columns]
        out.append([t.strftime('%Y-%m-%dT%H:%MZ'), t.astimezone(tz).strftime('%Y-%m-%d'), src[m],
                    ';'.join(labs), car] + vals + sds)
    return header, out, {'columns': columns + sd_cols, 'carrier_counts': counts, 'sessions': list(names)}


def main(argv=None):
    ap = argparse.ArgumentParser(description='per-minute feature table with episode labels')
    ap.add_argument('--data', default='data', help='folder holding one folder per session')
    ap.add_argument('--out', default='out', help='output folder (made private: mode 700)')
    ap.add_argument('--name', default='scene_minutes')
    ap.add_argument('--sessions', help='comma list of session folders instead of every one under --data')
    ap.add_argument('--episodes', help='episodes.csv with the labelled time ranges')
    ap.add_argument('--labels-map', help='json: which label words mean vehicle / bag-at-rest / bag-carried / desk')
    ap.add_argument('--tz', default='UTC', help='time zone of the local day used to hold days out, e.g. Europe/Paris')
    ap.add_argument('--imu-cal', help='IMU calibration json (optional)')
    ap.add_argument('--mag-cal', help='magnetometer calibration json (optional)')
    a = ap.parse_args(argv)
    lmap = DEFAULT_LABELS_MAP
    if a.labels_map:
        with open(a.labels_map) as fh:
            lmap = json.load(fh)
    ctx = Context(orient.load_channels(a.imu_cal), orient.load_channels(a.mag_cal))
    names = session_names(a.data, a.sessions.split(',') if a.sessions else None)
    header, rows, info = build(a.data, names, load_episodes(a.episodes), lmap, ZoneInfo(a.tz), ctx)
    os.makedirs(a.out, exist_ok=True)
    os.chmod(a.out, 0o700)
    path = os.path.join(a.out, a.name + '.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    os.chmod(path, 0o600)
    info.update(label_columns=['labels', 'carrier'], tz=a.tz,
                note='medians per minute (+ _sd spreads); no clock feature by design; carrier=desk derives from '
                     'mains power, so sys_plugged/sys_batt are never inputs')
    with open(os.path.join(a.out, a.name + '.columns.json'), 'w') as fh:
        json.dump(info, fh, indent=1)
    print(f'{len(rows)} minutes, {len(info["columns"])} columns, carrier counts {info["carrier_counts"]} -> {path}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
