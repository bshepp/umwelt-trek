#!/usr/bin/env python3
"""Calibrate a line after training: is its number a probability, or only a ranking?

    python -m umwelt_trek.calibrate PACKET [...]        # the folder probe.py wrote

Reads the packet's beliefs.csv (held-out per-minute probabilities) and fits a monotone re-mapping of them,
leave-one-local-day-out again so the map is never scored on its own day:
  * binary lines:  Platt  (logit p' = a * logit p + b)  and  temperature  (logit p' = logit p / T)
  * multiclass:    temperature on the class log-probabilities, renormalised
The method with the lower held-out log-loss wins. Writes calib.json (method, parameters, scores before and
after, a 10-bin reliability table) and beliefs_cal.csv into the packet.

The ranking (AUC) is unchanged by construction. What changes is whether the number can be believed: a line
whose calibrated log-loss beats the constant predictor gives a probability; one that does not gives only a
ranking, and its card should say so.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

EPS = 1e-4


def logit(p):
    p = np.clip(p, EPS, 1 - EPS); return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -500, 500)))


def ll_bin(p, y):
    p = np.clip(p, EPS, 1 - EPS); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit_platt(z, y, iters=200):
    """Newton on (a, b) for y ~ sigmoid(a z + b) with a weak ridge so a lone day cannot blow it up."""
    a, b = 1.0, 0.0
    X = np.stack([z, np.ones_like(z)], 1)
    w = np.array([a, b]); lam = 1e-2
    for _ in range(iters):
        p = sigmoid(X @ w)
        g = X.T @ (p - y) / len(y) + lam * (w - np.array([1.0, 0.0]))
        H = (X * (p * (1 - p))[:, None]).T @ X / len(y) + lam * np.eye(2)
        step = np.linalg.solve(H, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(w[0]), float(w[1])


def fit_temp_bin(z, y):
    best = (None, None)
    for T in np.exp(np.linspace(np.log(0.2), np.log(20), 121)):
        l = ll_bin(sigmoid(z / T), y)
        if best[0] is None or l < best[0]:
            best = (l, float(T))
    return best[1]


def calibrate_binary(rows):
    y = np.array([float(r['y']) for r in rows]); p = np.array([float(r['p']) for r in rows])
    days = np.array([r['day_local'] for r in rows]); z = logit(p)
    out = {'platt': np.zeros_like(p), 'temp': np.zeros_like(p)}
    for d in sorted(set(days)):
        tr, te = days != d, days == d
        if y[tr].sum() == 0 or y[tr].sum() == tr.sum():
            out['platt'][te] = p[te]; out['temp'][te] = p[te]; continue
        a, b = fit_platt(z[tr], y[tr]); out['platt'][te] = sigmoid(a * z[te] + b)
        T = fit_temp_bin(z[tr], y[tr]); out['temp'][te] = sigmoid(z[te] / T)
    const = ll_bin(np.full_like(p, y.mean()), y)
    scores = {'logloss_before': ll_bin(p, y), 'logloss_constant': const,
              'logloss_platt': ll_bin(out['platt'], y), 'logloss_temp': ll_bin(out['temp'], y),
              'brier_before': float(np.mean((p - y) ** 2)), 'brier_platt': float(np.mean((out['platt'] - y) ** 2)),
              'brier_temp': float(np.mean((out['temp'] - y) ** 2)), 'positives': int(y.sum()), 'minutes': int(len(y)),
              'days': int(len(set(days)))}
    method = 'platt' if scores['logloss_platt'] <= scores['logloss_temp'] else 'temp'
    pc = out[method]
    a, b = fit_platt(z, y); T = fit_temp_bin(z, y)                 # the full-fit parameters to ship
    params = {'a': a, 'b': b} if method == 'platt' else {'T': T}
    for nm, q in (('before', p), ('after', pc)):
        scores[f'precision_at_half_{nm}'] = float(((q >= 0.5) & (y == 1)).sum() / max(1, (q >= 0.5).sum()))
        scores[f'recall_at_half_{nm}'] = float(((q >= 0.5) & (y == 1)).sum() / max(1, (y == 1).sum()))
    scores['reliability_after'] = reliability(pc, y); scores['reliability_before'] = reliability(p, y)
    return method, params, scores, pc, None


def reliability(p, y, bins=10):
    tab = []
    edges = np.linspace(0, 1, bins + 1)
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= 1)
        if m.sum():
            tab.append({'bin': f'{edges[i]:.1f}-{edges[i+1]:.1f}', 'n': int(m.sum()), 'mean_p': round(float(p[m].mean()), 3),
                        'frac_pos': round(float(y[m].mean()), 3)})
    return tab


def calibrate_multi(rows, classes):
    P = np.array([[float(r['p_' + c]) for c in classes] for r in rows]); P = np.clip(P, EPS, 1)
    yi = np.array([classes.index(r['y']) for r in rows]); days = np.array([r['day_local'] for r in rows])
    L = np.log(P)
    def ll(Q): return float(-np.mean(np.log(np.clip(Q[np.arange(len(yi)), yi], EPS, 1))))
    def apply(T, Lx):
        Z = Lx / T; Z -= Z.max(1, keepdims=True); Q = np.exp(Z); return Q / Q.sum(1, keepdims=True)
    Ts = np.exp(np.linspace(np.log(0.2), np.log(20), 121))
    Pc = np.zeros_like(P)
    for d in sorted(set(days)):
        tr, te = days != d, days == d
        best = min(Ts, key=lambda T: float(-np.mean(np.log(np.clip(apply(T, L[tr])[np.arange(tr.sum()), yi[tr]], EPS, 1)))))
        Pc[te] = apply(best, L[te])
    prior = np.bincount(yi, minlength=len(classes)) / len(yi)
    T_full = min(Ts, key=lambda T: float(-np.mean(np.log(np.clip(apply(T, L)[np.arange(len(yi)), yi], EPS, 1)))))
    scores = {'logloss_before': ll(P), 'logloss_constant': float(-np.mean(np.log(prior[yi]))), 'logloss_temp': ll(Pc),
              'accuracy_before': float((P.argmax(1) == yi).mean()), 'accuracy_after': float((Pc.argmax(1) == yi).mean()),
              'minutes': int(len(yi)), 'days': int(len(set(days))), 'classes': {}}
    for k, c in enumerate(classes):
        for nm, Q in (('before', P), ('after', Pc)):
            pred = Q.argmax(1) == k; true = yi == k
            scores['classes'].setdefault(c, {})[nm] = {'precision': float((pred & true).sum() / max(1, pred.sum())),
                                                       'recall': float((pred & true).sum() / max(1, true.sum()))}
    return 'temp', {'T': float(T_full)}, scores, None, Pc


def calibrate_packet(pk, log=print):
    with open(os.path.join(pk, 'beliefs.csv')) as fh:
        rows = list(csv.DictReader(fh))
    hdr = rows[0].keys()
    if 'p' in hdr:
        method, params, scores, pc, Pc = calibrate_binary(rows)
    else:
        classes = [k[2:] for k in hdr if k.startswith('p_')]
        method, params, scores, pc, Pc = calibrate_multi(rows, classes)
    with open(os.path.join(pk, 'calib.json'), 'w') as fh:
        json.dump({'method': method, 'params': params, 'scores': scores,
                   'fitted': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, fh, indent=1)
    with open(os.path.join(pk, 'beliefs_cal.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        if pc is not None:
            w.writerow(['minute_utc', 'session', 'y', 'p', 'p_cal'])
            for r, q in zip(rows, pc):
                w.writerow([r['minute_utc'], r['session'], r['y'], r['p'], f'{q:.4f}'])
        else:
            w.writerow(['minute_utc', 'session', 'y'] + ['pcal_' + c for c in classes])
            for r, q in zip(rows, Pc):
                w.writerow([r['minute_utc'], r['session'], r['y']] + [f'{x:.4f}' for x in q])
    name = os.path.basename(os.path.dirname(os.path.abspath(pk)))
    s = scores
    if pc is not None:
        after = s['logloss_platt'] if method == 'platt' else s['logloss_temp']
        verdict = 'probability can be believed' if after < s['logloss_constant'] else 'ranking only'
        log(f"{name:22s} {method:5s} {params}  log-loss {s['logloss_before']:.3f} -> {after:.3f} "
            f"(constant {s['logloss_constant']:.3f}): {verdict}")
        log('   reliability after: ' + '  '.join(f"{b['bin']}:{b['frac_pos']:.2f}(n{b['n']})" for b in s['reliability_after']))
    else:
        verdict = 'probability can be believed' if s['logloss_temp'] < s['logloss_constant'] else 'ranking only'
        log(f"{name:22s} temp T={params['T']:.2f}  log-loss {s['logloss_before']:.3f} -> {s['logloss_temp']:.3f} "
            f"(constant {s['logloss_constant']:.3f}): {verdict};  accuracy {s['accuracy_before']:.3f} -> {s['accuracy_after']:.3f}")
        for c, v in s['classes'].items():
            log(f"   {c:12s} P/R {v['before']['precision']:.2f}/{v['before']['recall']:.2f} -> {v['after']['precision']:.2f}/{v['after']['recall']:.2f}")
    return method, params, scores


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.exit(__doc__)
    for pk in args:
        calibrate_packet(pk)


if __name__ == '__main__':
    main()
