#!/usr/bin/env python3
"""Train and score one line: a logistic regression that turns a minute of sensor summaries into the
probability of one state.

    python -m umwelt_trek.probe --csv out/scene_minutes.csv --zoo out/zoo --target carrier
    python -m umwelt_trek.probe --csv ... --zoo ... --event dawn --exclude sys_,usb_,hue_,light_,opt_ --no-presence
    python -m umwelt_trek.probe --csv ... --zoo ... --event waterfall --exclude sys_,usb_ --dropout 0.5 --no-presence

  --target carrier     multiclass over the table's `carrier` column
  --event WORD         binary: minutes whose labels contain WORD against every other labelled minute
  --negatives WORD     restrict the negatives to minutes carrying that label (same context)
  --event dawn         derived label: within 30 minutes of the day's 10-lux onset in the light columns. The
                       light columns make the label and are then left out of the inputs with --exclude
  --exclude a_,b_      column prefixes to leave out (the sensor that would make the label obvious; my habits)
  --drop-groups a,b    leave out whole sensor groups (ablation)
  --dropout 0.3        presence dropout: a share of training rows is repeated with one sensor group blanked
  --no-presence        leave out the has_<group> flags. For a rare event, "this sensor was along that day"
                       predicts the event without sensing anything; the flags are that leak

Scoring is leave-one-local-day-out: train on every other day, score the day held out. Minutes within a day
are too alike to split at random. Reported against the constant predictor: log-loss, Brier, AUC.

Written into <zoo>/<name>/<time>/: model.json (the line, see predict.py) and beliefs.csv (the held-out
probability of every scored minute). beliefs.csv is a diary of the days it covers. Keep it private.
"""
import argparse
import csv
import json
import os
import sys
import time
import warnings
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from .windows import build, load_table, standardise

GROUPS = ('aud_laptop', 'aud_c920', 'aud_usb', 'ble', 'wifi', 'rad', 'spec', 'sys', 'usb', 'hue', 'light', 'opt',
          'imu', 'gps_ub', 'gps_sirf')
LIGHT_COLS = ('light_loglux', 'opt_loglux')


def stamp(minute, fmt='%Y-%m-%dT%H:%MZ'):
    return datetime.fromtimestamp(int(minute) * 60, timezone.utc).strftime(fmt)


def dawn_label(X, cols, meta, log=print):
    """Positive within 30 min of the first minute of each local day where the 5-minute median light crosses
    10 lux, stays above it for 10 minutes, and was below it just before. A day whose light record begins
    after first light has no onset and gives only negatives. -> (y, rows that have a light reading)."""
    y = np.zeros(len(X)); has = np.zeros(len(X), dtype=bool)
    lcol = [cols.index(c) for c in LIGHT_COLS if c in cols]
    if not lcol:
        return y, has
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        lux = np.nanmax(X[:, lcol], axis=1) if len(lcol) > 1 else X[:, lcol[0]]
    onsets = {}
    for d in sorted(set(meta['day'])):
        idx = np.where(meta['day'] == d)[0]
        idx = idx[np.isfinite(lux[idx])]
        if len(idx) < 60:
            continue
        has[idx] = True
        m, v = meta['minute'][idx], lux[idx]
        for p in range(2, len(idx) - 10):
            med = np.median(v[p - 2:p + 3])
            if med >= 1.0 and np.all([np.median(v[q - 2:q + 3]) >= 1.0 for q in range(p, min(p + 10, len(idx) - 2))]) \
                    and np.median(v[max(0, p - 7):p - 2]) < 1.0:
                onsets[d] = m[p]
                break
    for i in range(len(X)):
        o = onsets.get(meta['day'][i])
        if o is not None and abs(meta['minute'][i] - o) <= 30:
            y[i] = 1.0
    log(f'dawn onsets found on {len(onsets)} of {len(set(meta["day"]))} days; {int(y.sum())} positive minutes')
    return y, has


def augment(F, names, y, p, rng):
    """Presence dropout: for a share p of training rows, add a copy with one present sensor group blanked."""
    if p <= 0:
        return F, y
    gcols = {g: [j for j, n in enumerate(names) if n.startswith(g + '_')] for g in GROUPS}
    gflag = {g: names.index('has_' + g) for g in GROUPS if 'has_' + g in names}
    pick = rng.random(len(F)) < p
    extra, ey = [], []
    for i in np.where(pick)[0]:
        present = [g for g in gflag if F[i, gflag[g]] > 0]
        if not present:
            continue
        g = present[rng.integers(len(present))]
        row = F[i].copy(); row[gcols[g]] = np.nan; row[gflag[g]] = 0.0
        extra.append(row); ey.append(y[i])
    if not extra:
        return F, y
    return np.vstack([F, np.array(extra)]), np.concatenate([y, np.array(ey)])


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p, y):
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    npos, nneg = y.sum(), len(y) - y.sum()
    if npos == 0 or nneg == 0:
        return float('nan')
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def episodes_of(mask, minutes):
    """Runs of positive minutes (gap <= 5 min) -> list of index arrays."""
    idx = np.where(mask)[0]
    runs, cur = [], []
    for i in idx:
        if cur and minutes[i] - minutes[cur[-1]] > 5:
            runs.append(np.array(cur)); cur = []
        cur.append(i)
    if cur:
        runs.append(np.array(cur))
    return runs


def main(argv=None):
    from sklearn.linear_model import LogisticRegression
    warnings.filterwarnings('ignore')
    ap = argparse.ArgumentParser(description='train and score one scene line, leave-one-local-day-out')
    ap.add_argument('--csv', default=os.path.join('out', 'scene_minutes.csv'))
    ap.add_argument('--zoo', default=os.path.join('out', 'zoo'), help='where packets are written')
    ap.add_argument('--target', default=None, help='multiclass column (carrier)')
    ap.add_argument('--event', default=None, help='binary: a label word, or dawn')
    ap.add_argument('--negatives', default=None, help='restrict negatives to minutes with this label')
    ap.add_argument('--exclude', default='', help='comma list of column prefixes to leave out')
    ap.add_argument('--drop-groups', default='', help='comma list of sensor groups to leave out')
    ap.add_argument('--dropout', type=float, default=0.0)
    ap.add_argument('--C', type=float, default=0.03, help='inverse regularisation strength')
    ap.add_argument('--name', default=None, help='line name (default: the target or event)')
    ap.add_argument('--no-presence', action='store_true', help='leave out the has_<group> flags')
    a = ap.parse_args(argv)
    if not a.target and not a.event:
        ap.error('--target or --event')
    name = a.name or (a.event or a.target)
    excl = [x for x in a.exclude.split(',') if x]
    dropg = [x for x in a.drop_groups.split(',') if x]
    rng = np.random.default_rng(0)
    classes = None
    if a.event == 'dawn':
        cols, X, meta = load_table(a.csv, excl, dropg, keep_cols=LIGHT_COLS)
        y, keep = dawn_label(X, cols, meta)
        y = y[keep]; X = X[keep]; meta = {k: v[keep] for k, v in meta.items()}
        lab = [j for j, c in enumerate(cols) if c in LIGHT_COLS and c.startswith(tuple(g + '_' for g in dropg) + tuple(excl))]
        if lab:
            X = np.delete(X, lab, axis=1); cols = [c for j, c in enumerate(cols) if j not in lab]
    else:
        cols, X, meta = load_table(a.csv, excl, dropg)
        if a.event:
            labs = [set(l.split(';')) if l else set() for l in meta['labels']]
            pos = np.array([a.event in L for L in labs])
            if a.negatives:
                keep = pos | np.array([a.negatives in L for L in labs])
            else:
                keep = pos | (meta['carrier'] != '') | (meta['labels'] != '')
            X = X[keep]; meta = {k: v[keep] for k, v in meta.items()}
            y = pos[keep].astype(float)
        else:
            keep = meta[a.target] != ''
            X = X[keep]; meta = {k: v[keep] for k, v in meta.items()}
            y = meta[a.target]; classes = sorted(set(y))
    print(f'{len(y)} minutes, {len(cols)} columns; ' + (f'classes {dict(Counter(y))}' if classes else f'positives {int(y.sum())}'))
    names, F = build(cols, X, meta['minute'], meta['session'])
    if a.no_presence:
        keepj = [j for j, n in enumerate(names) if not n.startswith('has_')]
        F = F[:, keepj]; names = [names[j] for j in keepj]
    days = meta['day']
    P = np.full((len(y), len(classes) if classes else 1), np.nan)
    for d in sorted(set(days)):
        te, tr = days == d, days != d
        ytr = y[tr]
        if te.sum() == 0 or len(set(ytr)) < 2:
            continue
        Ftr, ytr = augment(F[tr], names, ytr, a.dropout, rng)
        Ftr, Fte = standardise(Ftr, F[te])
        clf = LogisticRegression(C=a.C, class_weight='balanced', max_iter=2000)
        clf.fit(Ftr, ytr)
        pr = clf.predict_proba(Fte)
        P[te] = pr if classes else pr[:, list(clf.classes_).index(1.0)][:, None]
    ok = np.isfinite(P[:, 0])
    if not ok.any():
        sys.exit('no fold could be scored (every day lacks a second class): nothing to probe')
    out = {'name': name, 'minutes': int(len(y)), 'columns': len(names), 'exclude': excl, 'drop_groups': dropg,
           'dropout': a.dropout, 'C': a.C, 'days': len(set(days)), 'scored_minutes': int(ok.sum()),
           'no_presence': a.no_presence}
    if classes:
        pred = np.array(classes)[P[ok].argmax(axis=1)]; yt = y[ok]
        out['accuracy'] = float((pred == yt).mean()); out['majority'] = float(max(Counter(yt).values()) / len(yt))
        out['classes'] = {}
        print(f'\nleave-one-day-out: accuracy {out["accuracy"]:.3f} (majority {out["majority"]:.3f}) on {ok.sum()} minutes')
        print('%-14s %8s %8s %8s %8s' % ('class', 'n', 'prec', 'recall', 'logloss'))
        for i, c in enumerate(classes):
            tp = ((pred == c) & (yt == c)).sum(); fp = ((pred == c) & (yt != c)).sum(); fn = ((pred != c) & (yt == c)).sum()
            ll = logloss(P[ok][:, i], (yt == c).astype(float))
            out['classes'][c] = {'n': int((yt == c).sum()), 'precision': float(tp / max(tp + fp, 1)),
                                 'recall': float(tp / max(tp + fn, 1)), 'logloss': ll}
            print('%-14s %8d %8.3f %8.3f %8.3f' % (c, (yt == c).sum(), tp / max(tp + fp, 1), tp / max(tp + fn, 1), ll))
        print('\nconfusion (rows true, cols predicted):')
        for c in classes:
            print('%-14s' % c + ''.join('%12d' % ((yt == c) & (pred == p)).sum() for p in classes))
    else:
        p, yt = P[ok, 0], y[ok]
        base = float(yt.mean())
        out.update(logloss=logloss(p, yt), logloss_constant=logloss(np.full_like(p, base), yt),
                   brier=float(np.mean((p - yt) ** 2)), brier_constant=float(np.mean((base - yt) ** 2)), auc=auc(p, yt),
                   positives=int(yt.sum()))
        tp = ((p >= 0.5) & (yt == 1)).sum(); fp = ((p >= 0.5) & (yt == 0)).sum(); fn = ((p < 0.5) & (yt == 1)).sum()
        out.update(precision_at_half=float(tp / max(tp + fp, 1)), recall_at_half=float(tp / max(tp + fn, 1)))
        print(f'\nleave-one-day-out on {ok.sum()} minutes ({int(yt.sum())} positive):')
        print(f'  log-loss {out["logloss"]:.4f} (constant {out["logloss_constant"]:.4f})  Brier {out["brier"]:.4f} '
              f'(constant {out["brier_constant"]:.4f})  AUC {out["auc"]:.3f}  P/R at 0.5: {out["precision_at_half"]:.2f}/{out["recall_at_half"]:.2f}')
        runs = episodes_of(yt == 1, meta['minute'][ok])
        out['episodes'] = []
        print(f'  per positive episode ({len(runs)}): mean p / max p / minutes')
        for r in runs:
            m0 = stamp(meta['minute'][ok][r[0]], '%Y-%m-%d %H:%MZ')
            out['episodes'].append({'start': m0, 'minutes': int(len(r)), 'mean_p': float(p[r].mean()), 'max_p': float(p[r].max())})
            print(f'    {m0}  {p[r].mean():.2f} / {p[r].max():.2f} / {len(r)}')
        fpr = float(((p >= 0.5) & (yt == 0)).sum() / max((yt == 0).sum(), 1))
        out['false_positive_rate_at_half'] = fpr
        print(f'  false-positive rate at 0.5 on negatives: {fpr:.4f}')
    pk = os.path.join(a.zoo, name, time.strftime('%Y-%m-%dT%H%MZ', time.gmtime()))
    os.makedirs(pk, exist_ok=True)
    with open(os.path.join(pk, 'beliefs.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['minute_utc', 'session', 'day_local', 'y'] + ([f'p_{c}' for c in classes] if classes else ['p']))
        for i in np.where(ok)[0]:
            w.writerow([stamp(meta['minute'][i]), meta['session'][i], meta['day'][i], y[i]] + ['%.4f' % v for v in P[i]])
    Fa, _ = standardise(F, F)
    clf = LogisticRegression(C=a.C, class_weight='balanced', max_iter=2000).fit(Fa, y)
    mu = np.nanmean(F, axis=0); sd = np.nanstd(F, axis=0)
    sd = np.nan_to_num(sd, nan=1.0); sd[sd == 0] = 1.0
    with open(os.path.join(pk, 'model.json'), 'w') as fh:
        json.dump({'names': names, 'mu': np.nan_to_num(mu).tolist(), 'sd': sd.tolist(),
                   'coef': clf.coef_.tolist(), 'intercept': clf.intercept_.tolist(),
                   'classes': [str(c) for c in clf.classes_], 'scores': out}, fh)
    top = np.argsort(-np.abs(clf.coef_[0]))[:10]
    print('\nlargest weights (full fit): ' + ', '.join('%s %+.2f' % (names[j], clf.coef_[0][j]) for j in top))
    print(f'packet: {pk}')
    return pk


if __name__ == '__main__':
    main()
