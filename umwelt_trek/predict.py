#!/usr/bin/env python3
"""Apply a published line to a per-minute table.

    python -m umwelt_trek.predict --table out/scene_minutes.csv --model model.json [--calib calib.json] [--out p.csv]

A line is a logistic regression stored as plain numbers (model.json):

    names      the input names, in order (windows.py makes them)
    mu, sd     per-input mean and spread of the training rows
    coef, intercept, classes

    z = ((x - mu) / sd) @ coef.T + intercept          # a missing input counts as 0 after scaling
    binary line:      p = sigmoid(z)
    multiclass line:  p = softmax(z)

calib.json holds the map fitted afterwards on held-out days: `temp` divides the logit (or the class
log-probabilities) by T; `platt` is sigmoid(a * logit(p) + b).

An input the table lacks is treated as missing, so a line still runs when a sensor is absent. Whether it
still means anything is another matter: read the line's card for what it was trained on. The output is a
minute-by-minute record of someone's day. Keep it private.
"""
import argparse
import csv
import json
import sys

import numpy as np

from .windows import build, load_table

EPS = 1e-4


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -500, 500)))


def inputs_for(model, table_path):
    """Build every input the table can give and lay them out in the model's order. -> (F, meta, missing names)."""
    wanted = model['names']
    cols, X, meta = load_table(table_path)          # everything the table has; the model's names pick from it
    names, F = build(cols, X, meta['minute'], meta['session'])
    pos = {n: j for j, n in enumerate(names)}
    out = np.full((len(F), len(wanted)), np.nan)
    missing = []
    for j, n in enumerate(wanted):
        if n in pos:
            out[:, j] = F[:, pos[n]]
        else:
            missing.append(n)
    return out, meta, missing


def scores(model, F):
    mu = np.array(model['mu'], float); sd = np.array(model['sd'], float)
    sd[~np.isfinite(sd) | (sd == 0)] = 1.0          # an input that never varied in training carries no weight
    Z = np.nan_to_num((F - mu) / sd)
    return Z @ np.array(model['coef'], float).T + np.array(model['intercept'], float)


def probabilities(model, F, calib=None):
    """-> (classes, P) with one column per class; a binary line has the single column 'p'."""
    z = scores(model, F)
    method = (calib or {}).get('method'); par = (calib or {}).get('params') or {}
    if z.shape[1] == 1:
        p = sigmoid(z[:, 0])
        if method == 'temp':
            p = sigmoid(np.log(np.clip(p, EPS, 1 - EPS) / (1 - np.clip(p, EPS, 1 - EPS))) / par['T'])
        elif method == 'platt':
            q = np.clip(p, EPS, 1 - EPS)
            p = sigmoid(par['a'] * np.log(q / (1 - q)) + par['b'])
        return ['p'], p[:, None]
    z = z - z.max(axis=1, keepdims=True)
    P = np.exp(z); P /= P.sum(axis=1, keepdims=True)
    if method == 'temp':
        L = np.log(np.clip(P, EPS, 1)) / par['T']
        L -= L.max(axis=1, keepdims=True)
        P = np.exp(L); P /= P.sum(axis=1, keepdims=True)
    return ['p_' + c for c in model['classes']], P


def main(argv=None):
    ap = argparse.ArgumentParser(description='apply a published line to a per-minute table')
    ap.add_argument('--table', required=True)
    ap.add_argument('--model', required=True, help='model.json of the line')
    ap.add_argument('--calib', help='calib.json of the line (optional)')
    ap.add_argument('--out', help='csv to write (default: print a summary only)')
    a = ap.parse_args(argv)
    with open(a.model) as fh:
        model = json.load(fh)
    calib = None
    if a.calib:
        with open(a.calib) as fh:
            calib = json.load(fh)
    F, meta, missing = inputs_for(model, a.table)
    heads, P = probabilities(model, F, calib)
    print(f'{len(P)} minutes, {len(model["names"])} inputs, {len(missing)} of them not in this table'
          + (f' (e.g. {", ".join(missing[:4])})' if missing else ''), file=sys.stderr)
    for h, col in zip(heads, P.T):
        print(f'  {h}: mean {col.mean():.3f}, minutes above 0.5: {(col >= 0.5).sum()}', file=sys.stderr)
    if a.out:
        with open(a.out, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['minute_utc'] + heads)
            for t, row in zip(meta['minute_utc'], P):
                w.writerow([t] + ['%.4f' % v for v in row])
    return heads, P


if __name__ == '__main__':
    main()
