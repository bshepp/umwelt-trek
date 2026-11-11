"""Attitude of a sensor box from several IMU boards, and the magnetic field in the box frame.

The collector's IMU node sends one summary a second: per board (keyed by its multiplexer channel) the mean and
spread of acceleration (g) and rotation rate (deg/s), and per magnetometer the mean field. This module turns
those into one gravity vector, roll, pitch, which face is down, and a field vector with a quality verdict.

Box frame (right-handed): +X forward, +Y port, +Z up. Each board sits on a different wall, so each needs a
rotation from chip axes to box axes. FRAMES and MAG_FRAMES below are the rotations of my box; yours will
differ. Find them with a six-face test (the accelerometer axis that reads +1 g points up) and pass your own
tables to `attitude()` and `field()`, or edit them here.
"""
import json
import math

# a_box = M . a_chip, rows = box X, Y, Z in chip coordinates; keys = multiplexer channel of the board
FRAMES = {
    7: ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    5: ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    0: ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
}
# Magnetometers (QMC5883L). Chosen from the 24 proper signed permutations as the one that keeps the magnetic
# dip constant while the box is turned.
MAG_FRAMES = {
    1: ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
    6: ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    4: ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
}
MAG_LSB_PER_G = 3000.0
FACES = ('bottom', 'top', 'forward', 'aft', 'starboard', 'port')


def load_channels(path):
    """A calibration file is {"channels": {"<ch>": {...}}}; a missing or unreadable file means 'uncalibrated'."""
    if not path:
        return {}
    try:
        with open(path) as fh:
            return json.load(fh).get('channels', {})
    except (OSError, ValueError):
        return {}


def to_box(ch, v, frames=FRAMES):
    m = frames.get(int(ch))
    if m is None or v is None or len(v) < 3:
        return None
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def calibrated(ch, accel_g, gyro_dps, cal):
    c = cal.get(str(ch)) or {}
    b, s, gb = c.get('accel_bias_g', [0, 0, 0]), c.get('accel_scale', [1, 1, 1]), c.get('gyro_bias_dps', [0, 0, 0])
    a = [(accel_g[k] - b[k]) / (s[k] or 1.0) for k in range(3)] if accel_g else None
    g = [gyro_dps[k] - gb[k] for k in range(3)] if gyro_dps else None
    return a, g


def attitude(imus, cal=None, frames=FRAMES):
    """imus: the summary's 'imus' dict -> {'g': box gravity (up +), 'rate': box rates deg/s, 'roll', 'pitch',
    'down': face name, 'n': boards used, 'spread_g', 'norm'} or None."""
    cal = cal or {}
    gs, rs = [], []
    for ch, v in sorted(imus.items(), key=lambda kv: int(kv[0])):
        if not v.get('n') or not v.get('accel_g_mean'):
            continue
        a, g = calibrated(ch, v['accel_g_mean'], v.get('gyro_dps_mean'), cal)
        ab, gb = to_box(ch, a, frames), to_box(ch, g, frames)
        norm = math.sqrt(sum(x * x for x in a))
        if ab is not None and 0.5 < norm < 1.5:
            gs.append(ab)
            if gb:
                rs.append(gb)
    if not gs:
        return None
    g = [sum(v[k] for v in gs) / len(gs) for k in range(3)]
    r = [sum(v[k] for v in rs) / len(rs) for k in range(3)] if rs else [0.0, 0.0, 0.0]
    gx, gy, gz = g
    pitch = math.degrees(math.atan2(gx, math.sqrt(gy * gy + gz * gz)))     # nose up positive
    roll = math.degrees(math.atan2(gy, gz))                                # starboard side down positive
    faces = {'bottom': gz, 'top': -gz, 'forward': -gx, 'aft': gx, 'starboard': gy, 'port': -gy}
    down = max(faces, key=faces.get)
    spread = max(math.sqrt(sum((v[k] - g[k]) ** 2 for k in range(3))) for v in gs) if len(gs) > 1 else 0.0
    return {'g': g, 'rate': r, 'roll': roll, 'pitch': pitch, 'down': down, 'n': len(gs),
            'spread_g': spread, 'norm': math.sqrt(sum(x * x for x in g))}


def mag_to_box(ch, gauss_raw, magcal, frames=MAG_FRAMES):
    """The node's 'mag_gauss_mean' (raw counts / 3000) -> calibrated gauss in the box frame, or None."""
    m = frames.get(int(ch))
    c = magcal.get(str(ch))
    if m is None or not gauss_raw or len(gauss_raw) < 3:
        return None
    if c:
        o, sc = c['offset_counts'], c['scale']
        v = [((gauss_raw[k] * MAG_LSB_PER_G - o[k]) * sc[k]) / MAG_LSB_PER_G for k in range(3)]
    else:
        v = list(gauss_raw)
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def field(mags, att, magcal=None, frames=MAG_FRAMES):
    """mags: the summary's 'mags' dict; att: attitude() result (for gravity). -> {'B', 'norm', 'spread', 'n',
    'inclination': deg (down +), 'heading': deg (box +X from magnetic north, clockwise), 'quality'} or None."""
    magcal = magcal or {}
    vecs, norms = [], []
    for ch, v in sorted(mags.items(), key=lambda kv: int(kv[0])):
        b = mag_to_box(ch, v.get('mag_gauss_mean'), magcal, frames) if v.get('n') else None
        if b is None:
            continue
        norms.append(math.sqrt(sum(x * x for x in b)))
        vecs.append(b)
    if not vecs:
        return None
    B = [sum(v[i] for v in vecs) / len(vecs) for i in range(3)]
    norm = math.sqrt(sum(x * x for x in B))
    spread = (max(norms) - min(norms)) if norms else 0.0
    out = {'B': B, 'norm': norm, 'spread': spread, 'n': len(vecs), 'inclination': None, 'heading': None}
    g = att.get('g') if att else None
    if g and norm > 0:
        gn = math.sqrt(sum(x * x for x in g))
        if gn > 0:
            u = [x / gn for x in g]                               # up, unit
            dot = sum(B[i] * u[i] for i in range(3))
            out['inclination'] = math.degrees(math.asin(max(-1.0, min(1.0, -dot / norm))))
            h = [B[i] - dot * u[i] for i in range(3)]              # horizontal part = magnetic north in the box frame
            if math.sqrt(sum(x * x for x in h)) > 1e-6:
                out['heading'] = math.degrees(math.atan2(h[1], h[0])) % 360.0
    if norm < 0.25 or norm > 0.6:
        out['quality'] = 'bent'          # |B| far from the earth's field: iron nearby
    elif spread > 0.08:
        out['quality'] = 'gradient'      # the boards disagree
    else:
        out['quality'] = 'clean'
    return out
