"""Tests on invented records. Run from the repository root: python -m unittest discover tests"""
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from umwelt_trek import orient, predict, table, windows          # noqa: E402
from umwelt_trek.features import Context, record_features        # noqa: E402


def rec(sensor, data, instance=None, valid=True, t='2030-03-01T06:00:10Z'):
    r = {'sensor': sensor, 'started': t, 'valid': valid, 'data': data}
    if instance:
        r['instance'] = instance
    return r


class Features(unittest.TestCase):
    def test_no_identifier_or_position_comes_out(self):
        ctx = Context()
        r = rec('gps', {'mode': 3, 'satellites_used': 7, 'hdop': 1.1, 'speed': 1.2, 'lat': 12.34, 'lon': 56.78,
                        'sats_with_signal': 9, 'peak_signal_dbhz': 40}, 'u-blox-7')
        f = record_features(r, ctx)
        self.assertEqual(f['gps_ub_fix3d'], 1.0)
        self.assertFalse(any('lat' in k or 'lon' in k for k in f))
        self.assertNotIn(12.34, f.values())
        w = rec('wifi', {'networks': [{'bssid_h': 'aa', 'rssi': -50, 'channel': 36}, {'bssid_h': 'bb', 'rssi': -80, 'channel': 1}]})
        f = record_features(w, ctx)
        self.assertTrue(all(isinstance(v, (int, float)) for v in f.values()))
        self.assertEqual(f['wifi_5ghz_share'], 0.5)

    def test_churn_needs_a_previous_scan_and_resets_per_session(self):
        ctx = Context()
        scan = lambda ids: rec('bluetooth', {'scans': [{'kind': 'ble', 'device_count': len(ids),
                                                        'devices': [{'id': i} for i in ids]}]})
        self.assertNotIn('ble_new_frac', record_features(scan(['a', 'b']), ctx))
        self.assertEqual(record_features(scan(['a', 'c']), ctx)['ble_new_frac'], 0.5)
        ctx.new_session()
        self.assertNotIn('ble_new_frac', record_features(scan(['x']), ctx))

    def test_invalid_record_gives_no_levels(self):
        self.assertEqual(record_features(rec('light', {'lux': 5, 'full': 10, 'ir': 2}, valid=False), Context()), {})

    def test_optical_shares_sum_to_one(self):
        f = record_features(rec('optical', {'tsl': {'lux': 99.99, 'full': 100, 'ir': 25},
                                            'as7341': {'raw': [1, 2, 3, 4, 5, 6, 7, 8], 'clear': 20, 'gain': 16, 'astep': 599, 'atime': 29},
                                            'ltr': {'uvi': 0.5, 'lux': 80}}), Context())
        self.assertAlmostEqual(f['opt_loglux'], 2.0)
        self.assertAlmostEqual(sum(v for k, v in f.items() if k.startswith('opt_f')), 1.0)
        self.assertEqual(f['opt_ir_share'], 0.25)


class Orient(unittest.TestCase):
    def test_level_box_reads_bottom_down(self):
        # board on channel 0: chip Z is box Z, so +1 g on chip Z means the bottom is down
        att = orient.attitude({'0': {'n': 50, 'accel_g_mean': [0, 0, 1.0], 'gyro_dps_mean': [0, 0, 0]}})
        self.assertEqual(att['down'], 'bottom')
        self.assertAlmostEqual(att['roll'], 0.0); self.assertAlmostEqual(att['pitch'], 0.0)

    def test_frames_are_proper_rotations(self):
        for m in list(orient.FRAMES.values()) + list(orient.MAG_FRAMES.values()):
            self.assertAlmostEqual(float(np.linalg.det(np.array(m, float))), 1.0)


class Windows(unittest.TestCase):
    def test_window_means_stop_at_a_gap_and_at_a_session_change(self):
        X = np.array([[1.0], [3.0], [5.0], [7.0]])
        minutes = np.array([0, 1, 50, 51]); sess = np.array(['a', 'a', 'a', 'b'])
        names, F = windows.build(['wifi_networks'], X, minutes, sess)
        self.assertEqual(names, ['wifi_networks', 'wifi_networks_m10', 'wifi_networks_m30', 'has_wifi'])
        self.assertEqual(list(F[:, 1]), [1.0, 2.0, 5.0, 7.0])

    def test_missing_becomes_zero_after_scaling(self):
        tr = np.array([[1.0, np.nan], [3.0, np.nan]])
        a, b = windows.standardise(tr, np.array([[np.nan, 4.0]]))
        self.assertEqual(b.tolist(), [[0.0, 4.0]])


class Predict(unittest.TestCase):
    def test_formula_and_zero_spread(self):
        model = {'names': ['a', 'b'], 'mu': [1.0, 5.0], 'sd': [2.0, 0.0], 'coef': [[1.0, 3.0]], 'intercept': [0.5],
                 'classes': ['0.0', '1.0']}
        F = np.array([[3.0, 5.0], [np.nan, 6.0]])
        heads, P = predict.probabilities(model, F)
        self.assertEqual(heads, ['p'])
        self.assertAlmostEqual(P[0, 0], 1 / (1 + math.exp(-1.5)))            # (3-1)/2 + 0 + 0.5
        self.assertAlmostEqual(P[1, 0], 1 / (1 + math.exp(-3.5)))            # missing a -> 0; (6-5)/1*3 + 0.5
        _, Pc = predict.probabilities(model, F, {'method': 'temp', 'params': {'T': 2.0}})
        self.assertAlmostEqual(Pc[0, 0], 1 / (1 + math.exp(-0.75)))

    def test_multiclass_rows_sum_to_one(self):
        model = {'names': ['a'], 'mu': [0.0], 'sd': [1.0], 'coef': [[1.0], [0.0], [-1.0]], 'intercept': [0, 0, 0],
                 'classes': ['x', 'y', 'z']}
        heads, P = predict.probabilities(model, np.array([[2.0], [-2.0]]), {'method': 'temp', 'params': {'T': 1.7}})
        self.assertEqual(heads, ['p_x', 'p_y', 'p_z'])
        self.assertTrue(np.allclose(P.sum(axis=1), 1.0))
        self.assertEqual(P[0].argmax(), 0); self.assertEqual(P[1].argmax(), 2)


class EndToEnd(unittest.TestCase):
    def test_invented_days_through_the_whole_pipeline(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest('scikit-learn not installed')
        from umwelt_trek import calibrate, probe
        with tempfile.TemporaryDirectory() as w:
            subprocess.run([sys.executable, os.path.join(ROOT, 'examples', 'make_synthetic.py'), '--out', w, '--days', '3'],
                           check=True, capture_output=True)
            out = os.path.join(w, 'out')
            with open(os.devnull, 'w') as null:
                old = sys.stderr, sys.stdout
                sys.stderr = sys.stdout = null
                try:
                    table.main(['--data', os.path.join(w, 'sessions'), '--out', out, '--episodes', os.path.join(w, 'episodes.csv')])
                    pk = probe.main(['--csv', os.path.join(out, 'scene_minutes.csv'), '--zoo', os.path.join(out, 'zoo'),
                                     '--event', 'dawn', '--exclude', 'sys_,usb_,light_,opt_', '--no-presence'])
                    calibrate.calibrate_packet(pk, log=lambda *a: None)
                    heads, P = predict.main(['--table', os.path.join(out, 'scene_minutes.csv'),
                                             '--model', os.path.join(pk, 'model.json'), '--calib', os.path.join(pk, 'calib.json')])
                finally:
                    sys.stderr, sys.stdout = old
            with open(os.path.join(out, 'scene_minutes.csv')) as fh:
                head = next(csv.reader(fh))
            self.assertEqual(head[:5], ['minute_utc', 'day_local', 'session', 'labels', 'carrier'])
            banned = {'lat', 'lon', 'latitude', 'longitude', 'hour', 'clock', 'time', 'bssid', 'mac', 'ssid', 'id'}
            self.assertFalse([c for c in head[5:] if banned & set(c.split('_'))])
            self.assertEqual(oct(os.stat(out).st_mode & 0o777), '0o700')
            with open(os.path.join(pk, 'model.json')) as fh:
                m = json.load(fh)
            self.assertFalse(any(n.startswith(('light_', 'opt_', 'sys_', 'has_')) for n in m['names']))
            self.assertGreater(m['scores']['auc'], 0.7)
            self.assertEqual(P.shape, (3 * 1440, 1))
            self.assertTrue(((P >= 0) & (P <= 1)).all())


if __name__ == '__main__':
    unittest.main()
