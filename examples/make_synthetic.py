#!/usr/bin/env python3
"""Write a small invented data set in the collector's record format, so the pipeline can be run end to end
without anyone's real days.

    python examples/make_synthetic.py --out example_data [--days 6] [--seed 1]

It makes one session folder per day under <out>/sessions/, an episodes.csv with the labelled time ranges,
and nothing else. The world it invents is simple on purpose:

  * the machine sits on a desk on mains power, except for one walk and one bus ride a day, on battery;
  * the sun comes up at a slightly different minute each day. A light plate sees it (that makes the dawn
    label). The microphone hears a dawn chorus in its upper bands and the Bluetooth count creeps up as the
    neighbours wake, so a model that is denied the light can still find the dawn, imperfectly;
  * carried in a bag the microphone is louder, a GPS receiver gets a fix, and the WiFi and Bluetooth
    neighbourhood churns.

Every number here is made up. Nothing is measured, nobody's device is in it, and the results of training on
it say nothing about the published lines. It exists to show the formats and to test the code.
"""
import argparse
import hashlib
import json
import math
import os
import random
from datetime import datetime, timedelta, timezone

BANDS = ('sub_bass', 'bass', 'low_mid', 'mid', 'upper_mid', 'presence', 'brilliance', 'high', 'very_high')


def hid(rng_tag):
    return hashlib.sha256(rng_tag.encode()).hexdigest()[:12]


def rec(sensor, t, data, instance=None):
    r = {'sensor': sensor, 'timestamp': t.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), 'started': t.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
         'valid': True, 'data': data}
    if instance:
        r['instance'] = instance
    return r


def day_records(day0, rng, dawn_min, walk, bus):
    """Yield (time, record) for one invented day. walk/bus are (start_minute, end_minute)."""
    home_ble = [hid(f'home-ble-{i}') for i in range(9)]
    home_wifi = [hid(f'home-wifi-{i}') for i in range(14)]
    for m in range(1440):
        t = day0 + timedelta(minutes=m, seconds=rng.uniform(0, 20))
        carried = walk[0] <= m < walk[1]
        riding = bus[0] <= m < bus[1]
        away = carried or riding
        # the sun: a smooth rise around dawn_min, a fall around 12 hours later
        up = 1 / (1 + math.exp(-(m - dawn_min) / 6.0)) * 1 / (1 + math.exp((m - dawn_min - 690) / 6.0))
        lux = 0.05 + 9000 * up * rng.uniform(0.7, 1.1)
        if away:
            lux *= 0.02                                    # the plate is at the window, the bag is not
        chorus = math.exp(-((m - dawn_min - 5) / 28.0) ** 2)   # birds: a bump around first light
        awake = 1 / (1 + math.exp(-(m - dawn_min - 25) / 20.0))

        # system
        yield t, rec('system', t, {'cpu_temp_c': 55 + 10 * away + rng.gauss(0, 2), 'cpu_percent': 12 + rng.gauss(0, 4),
                                   'memory_percent': 31 + rng.gauss(0, 1), 'battery_percent': 100 - 20 * away,
                                   'battery_plugged_in': not away, 'fan_rpm': 2800 + 600 * away + rng.gauss(0, 80),
                                   'cpu_load_1m': 0.6 + rng.random() * 0.4, 'net_packets_sent': 40, 'net_packets_recv': 55})
        # microphone, already reduced to band levels by the collector
        base = -62 + 14 * carried + 20 * riding
        bands = {}
        for i, b in enumerate(BANDS):
            lvl = base - 2.5 * i + rng.gauss(0, 1.5)
            if b in ('presence', 'brilliance', 'upper_mid'):
                lvl += 9 * chorus * rng.uniform(0.3, 1.2)
            if riding and b in ('sub_bass', 'bass'):
                lvl += 12
            bands[b] = {'avg_db': lvl, 'max_db': lvl + 4 + 6 * chorus * rng.random() + 5 * carried}
        rms = 10 ** ((base + 8 + rng.gauss(0, 1.5)) / 20)
        yield t, rec('audio_spectrum', t, {'rms': rms, 'peak': rms * 4, 'bands': bands,
                                            'features': {'centroid_hz': 900 + 1500 * chorus + 600 * carried + rng.gauss(0, 80),
                                                         'flatness': 0.2 + 0.1 * rng.random()}}, 'laptop-mic')
        # Bluetooth: counts, signal statistics and salted hashes only
        n_extra = int(rng.random() * 3 + 6 * awake * rng.random() + (25 * rng.random() if away else 0))
        devs = [{'id': x, 'company_ids': [rng.choice([6, 76, 117, 224])]} for x in home_ble if rng.random() < (0.25 if away else 0.9)]
        devs += [{'id': hid(f'pass-{day0.date()}-{m}-{i}'), 'company_ids': [rng.choice([6, 76, 76, 117, 224, 301])]} for i in range(n_extra)]
        rssi = sorted(rng.gauss(-78, 9) for _ in devs) or [-90]
        yield t, rec('bluetooth', t, {'scans': [{'kind': 'ble', 'device_count': len(devs), 'adverts_per_second': 2.5 * len(devs) + rng.random(),
                                                  'rssi': {'median': rssi[len(rssi) // 2], 'p25': rssi[len(rssi) // 4], 'p75': rssi[3 * len(rssi) // 4], 'max': rssi[-1]},
                                                  'named_devices': len(devs) // 5, 'address_types': {'public': len(devs) // 4, 'random': len(devs) - len(devs) // 4},
                                                  'devices': devs}]})
        # WiFi: hashed ids, channels, levels
        nets = [{'bssid_h': x, 'rssi': rng.gauss(-70, 8), 'channel': rng.choice([1, 6, 11, 36, 44, 149]), 'hidden': rng.random() < 0.1}
                for x in home_wifi if rng.random() < (0.1 if away else 0.92)]
        if away:
            nets += [{'bssid_h': hid(f'street-{day0.date()}-{m}-{i}'), 'rssi': rng.gauss(-76, 7), 'channel': rng.choice([1, 6, 11, 36, 149]),
                      'hidden': rng.random() < 0.15} for i in range(int(8 + 20 * rng.random()))]
        yield t, rec('wifi', t, {'network_count': len(nets), 'networks': nets})
        # one GPS receiver: quality only, the features never read a position
        fix = away and rng.random() < 0.85
        yield t, rec('gps', t, {'mode': 3 if fix else 1, 'satellites_used': int(6 + rng.random() * 5) if fix else 0,
                                'hdop': 1.2 + rng.random() if fix else None, 'speed': (1.3 if carried else 8.0) + rng.gauss(0, 0.3) if fix else None,
                                'sats_with_signal': int((9 if away else 3) + rng.random() * 4), 'peak_signal_dbhz': (38 if away else 24) + rng.gauss(0, 3)},
                  'u-blox-7')
        # light plate at the window
        raw = [max(0, int(lux * w * rng.uniform(0.9, 1.1))) for w in (0.4, 0.7, 0.9, 1.0, 1.2, 1.1, 0.9, 0.7)]
        yield t, rec('optical', t, {'tsl': {'full': int(lux * 12) + 20, 'ir': int(lux * 4) + 6, 'lux': lux},
                                    'as7341': {'raw': raw, 'clear': sum(raw) // 2, 'nir': int(lux * 0.5), 'gain': 16, 'astep': 599, 'atime': 29},
                                    'ltr': {'uvi': 0.0003 * lux, 'lux': lux * 0.9}})


def main():
    ap = argparse.ArgumentParser(description='write an invented data set in the collector record format')
    ap.add_argument('--out', default='example_data')
    ap.add_argument('--days', type=int, default=6)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    start = datetime(2030, 3, 1, tzinfo=timezone.utc)          # an invented week
    eps = [('start_utc', 'end_utc', 'labels', 'note')]
    for d in range(a.days):
        day0 = start + timedelta(days=d)
        dawn = 380 + rng.randint(-25, 25)                      # first light, minutes after midnight
        w0 = 480 + rng.randint(-30, 60); walk = (w0, w0 + rng.randint(25, 50))
        b0 = 1000 + rng.randint(-40, 40); bus = (b0, b0 + rng.randint(15, 30))
        name = 'day_' + day0.strftime('%Y%m%d')
        folder = os.path.join(a.out, 'sessions', name)
        os.makedirs(folder, exist_ok=True)
        files = {}
        for t, r in day_records(day0, rng, dawn, walk, bus):
            hour = t.strftime('%Y-%m-%d_%H')
            if hour not in files:
                files[hour] = open(os.path.join(folder, f'data_{hour}.jsonl'), 'w')
            files[hour].write(json.dumps(r) + '\n')
        for fh in files.values():
            fh.close()
        iso = lambda m: (day0 + timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%MZ')
        eps.append((iso(walk[0]), iso(walk[1]), 'walk;bag-carried', 'invented'))
        eps.append((iso(bus[0]), iso(bus[1]), 'bus;vehicle', 'invented'))
    with open(os.path.join(a.out, 'episodes.csv'), 'w') as fh:
        for row in eps:
            fh.write(','.join(row) + '\n')
    print(f'{a.days} invented days -> {a.out}/sessions, labels -> {a.out}/episodes.csv')


if __name__ == '__main__':
    main()
