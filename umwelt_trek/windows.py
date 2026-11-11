"""From table columns to model inputs.

A model input vector for one minute is: the minute's columns, their means over the last 10 and the last 30
minutes (inside the same session; a gap breaks the window), and one present/absent flag per sensor group
(`has_<group>`). Missing values stay NaN here; `standardise()` turns them into 0 after scaling, which is
"this sensor says nothing".

The order and names made here are the `names` list in every published model.json.
"""
import csv
import warnings
from datetime import datetime

import numpy as np

# groups that get a has_<group> flag. Later groups (opt, imu) have none: adding them would rename nothing but
# would change the input list of the published lines, so they are left out until those lines are retrained.
FLAG_GROUPS = ('aud_laptop', 'aud_c920', 'aud_usb', 'ble', 'wifi', 'rad', 'spec', 'sys', 'usb', 'hue', 'light',
               'gps_ub', 'gps_sirf')
ALWAYS_EXCLUDE = ('sys_plugged', 'sys_batt', 'wx_')   # the desk label comes from mains power; weather is a label source


def load_table(path, exclude=(), drop_groups=(), keep_cols=()):
    """-> (columns, X with NaN for empty cells, meta). The first five columns are bookkeeping, not inputs."""
    with open(path) as fh:
        r = csv.reader(fh)
        head = next(r)
        rows = list(r)
    excl = tuple(exclude) + ALWAYS_EXCLUDE + tuple(g + '_' for g in drop_groups)
    cols = [c for c in head[5:] if not c.startswith(excl) or c in keep_cols]
    ci = [head.index(c) for c in cols]
    X = np.full((len(rows), len(cols)), np.nan)
    meta = {'minute': [], 'minute_utc': [], 'day': [], 'session': [], 'labels': [], 'carrier': []}
    for i, row in enumerate(rows):
        for j, k in enumerate(ci):
            if row[k]:
                X[i, j] = float(row[k])
        meta['minute'].append(int(datetime.fromisoformat(row[0].replace('Z', '+00:00')).timestamp() // 60))
        meta['minute_utc'].append(row[0]); meta['day'].append(row[1]); meta['session'].append(row[2])
        meta['labels'].append(row[3]); meta['carrier'].append(row[4])
    return cols, X, {k: np.array(v) for k, v in meta.items()}


def build(cols, X, minutes, sess):
    """-> (names, F): the minute, the 10- and 30-minute means, the presence flags."""
    feats = [X]
    for w in (10, 30):
        acc = np.full_like(X, np.nan)
        for i in range(len(X)):
            lo = i
            while lo > 0 and minutes[i] - minutes[lo - 1] <= w and sess[lo - 1] == sess[i]:
                lo -= 1
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)      # a column with no value in the window stays NaN
                acc[i] = np.nanmean(X[lo:i + 1], axis=0)
        feats.append(acc)
    names = list(cols) + [c + '_m10' for c in cols] + [c + '_m30' for c in cols]
    flags = []
    for g in FLAG_GROUPS:
        gi = [j for j, c in enumerate(cols) if c.startswith(g + '_')]
        if gi:
            flags.append((~np.isnan(X[:, gi]).all(axis=1)).astype(float)); names.append('has_' + g)
    F = np.concatenate(feats + ([np.stack(flags, axis=1)] if flags else []), axis=1)
    return names, F


def standardise(Ftr, Fte):
    """Scale by the training rows' mean and spread; a missing value becomes 0."""
    mu = np.nanmean(Ftr, axis=0); sd = np.nanstd(Ftr, axis=0)
    sd[~np.isfinite(sd) | (sd == 0)] = 1.0; mu[~np.isfinite(mu)] = 0.0
    return np.nan_to_num((Ftr - mu) / sd), np.nan_to_num((Fte - mu) / sd)
