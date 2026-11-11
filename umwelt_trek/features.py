"""One collector record -> named numbers.

Every sensor writes one JSON object per measurement (docs/RECORDS.md). `record_features()` turns one of them
into a flat {column: value} dict of scalars. Only levels, counts, shares and spreads come out: no identifier,
no position, no clock. The table builder (table.py) then takes the median of each column over a minute.

Column prefixes name the sensor group: aud_<mic>_, ble_, wifi_, gps_<receiver>_, rad_, spec_, sys_, usb_,
hue_, light_, opt_, imu_. The models' `names` lists are made of these columns plus the window means that
windows.py adds.
"""
import math
import statistics as st

from . import orient

BANDS = ('sub_bass', 'bass', 'low_mid', 'mid', 'upper_mid', 'presence', 'brilliance', 'high', 'very_high')
MICS = ('laptop-mic', 'c920-mic', 'usb-mic')
AS7341_BANDS = ('415', '445', '480', '515', '555', '590', '630', '680')   # F1..F8 centre wavelengths, nm


class Context:
    """What the extractor needs besides the record: IMU calibrations (optional) and the per-session memory of
    the previous Bluetooth / WiFi scan, used for the churn features. Call `new_session()` between sessions."""

    def __init__(self, imu_cal=None, mag_cal=None):
        self.imu_cal = imu_cal or {}
        self.mag_cal = mag_cal or {}
        self.state = {}

    def new_session(self):
        self.state = {}


def _db(x):
    return 20 * math.log10(x) if isinstance(x, (int, float)) and x > 0 else None


def _norm(v):
    return math.sqrt(sum(x * x for x in v)) if v and len(v) >= 3 else None


def _scalars(out):
    return {k: v for k, v in out.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v)}


def receiver(rec):
    """Which GPS receiver a record is from: 'ub' (u-blox), 'sirf' (the laptop's internal one), or None."""
    inst = rec.get('instance') or (rec.get('data') or {}).get('device') or ''
    if 'u-blox' in inst or 'ttyACM' in inst:
        return 'ub'
    if 'FTDI' in inst or 'SiRF' in inst:
        return 'sirf'
    return None


def base_features(rec):
    """The first generation of columns (levels and counts). Needs a valid record."""
    s, d = rec.get('sensor'), rec.get('data') or {}
    if not rec.get('valid') or not d:
        return {}
    out = {}
    if s == 'light':
        lux = d.get('lux')
        if lux is not None and lux >= 0:
            out['light_loglux'] = math.log10(lux + 0.01)
        if d.get('full') and d.get('ir') is not None:
            out['light_ir_share'] = d['ir'] / d['full']
    elif s == 'hue':
        luma = d.get('luma') or {}
        out.update(hue_luma=luma.get('mean'), hue_luma_p95=luma.get('p95'), hue_cct=d.get('cct_k'),
                   hue_sat=d.get('sat'), hue_exposure=d.get('exposure_time'), hue_gain=d.get('gain'),
                   hue_level=d.get('level'), hue_clipped=(d.get('clipped') or {}).get('bright'),
                   hue_colorfulness=d.get('colorfulness'))
    elif s == 'audio_spectrum':
        m = rec.get('instance')
        if m not in MICS:
            return {}
        p = 'aud_' + m.replace('-mic', '') + '_'
        out[p + 'rms_db'] = _db(d.get('rms'))
        out[p + 'peak_db'] = _db(d.get('peak'))
        for b in BANDS:
            out[p + b] = (d.get('bands') or {}).get(b, {}).get('avg_db')
        f = d.get('features') or {}
        out[p + 'centroid'] = f.get('centroid_hz')
        out[p + 'flatness'] = f.get('flatness')
    elif s == 'bluetooth':
        for sc in d.get('scans') or []:
            if sc.get('kind') != 'ble':
                continue
            r = sc.get('rssi') or {}
            at = sc.get('address_types') or {}
            out.update(ble_devices=sc.get('device_count'), ble_adverts_s=sc.get('adverts_per_second'),
                       ble_rssi_med=r.get('median'), ble_rssi_p25=r.get('p25'), ble_rssi_p75=r.get('p75'),
                       ble_rssi_max=r.get('max'), ble_named=sc.get('named_devices'),
                       ble_public=at.get('public'), ble_random=at.get('random'))
    elif s == 'wifi':
        nets = d.get('networks') or []
        rs = [n.get('rssi') for n in nets if isinstance(n.get('rssi'), (int, float))]
        out['wifi_networks'] = d.get('network_count', len(nets))
        if rs:
            out['wifi_rssi_med'] = st.median(rs)
            out['wifi_near'] = sum(1 for x in rs if x > -60)
            out['wifi_rssi_max'] = max(rs)
    elif s == 'radiation':
        out['rad_cpm'] = d.get('cpm')
    elif s == 'spectrum':
        out['spec_active'] = d.get('above_baseline_count')
        ext = [x.get('excess_db') for x in d.get('strongest_signals') or []
               if not x.get('internal') and isinstance(x.get('excess_db'), (int, float))]
        if ext:
            out['spec_top_excess'] = max(ext)
            out['spec_mean_excess'] = sum(ext) / len(ext)
    elif s == 'system':
        out.update(sys_cpu_temp=d.get('cpu_temp_c'), sys_cpu=d.get('cpu_percent'), sys_mem=d.get('memory_percent'),
                   sys_batt=d.get('battery_percent'),
                   sys_plugged=(None if d.get('battery_plugged_in') is None else int(bool(d['battery_plugged_in']))))
    elif s == 'usb_monitor':
        out['usb_devices'] = d.get('usb_device_count')
    return _scalars(out)


def scene_features(rec, ctx):
    """The second generation: per-receiver GPS quality, sound texture, device churn, the IMU box, the light plate."""
    s, d = rec.get('sensor'), rec.get('data') or {}
    state = ctx.state
    out = {}
    if s == 'gps' and d:
        r = receiver(rec)
        if r is None:
            return {}
        p = f'gps_{r}_'
        mode = d.get('mode') or 1
        out[p + 'fix'] = 1.0 if mode >= 2 else 0.0
        out[p + 'fix3d'] = 1.0 if mode >= 3 else 0.0
        if mode >= 2:
            out[p + 'sats'] = d.get('satellites_used')
            out[p + 'hdop'] = d.get('hdop')
            out[p + 'speed'] = d.get('speed')
        out[p + 'sig'] = d.get('sats_with_signal')
        out[p + 'peak_snr'] = d.get('peak_signal_dbhz')
    elif s == 'audio_spectrum' and rec.get('valid') and d:
        m = rec.get('instance') or ''
        if m not in MICS:
            return {}
        p = 'aud_' + m.replace('-mic', '') + '_'
        b = d.get('bands') or {}
        hi = [b.get(k, {}) for k in ('presence', 'brilliance')]
        mods = [x['max_db'] - x['avg_db'] for x in hi if isinstance(x.get('max_db'), (int, float))
                and isinstance(x.get('avg_db'), (int, float))]
        if mods:
            out[p + 'mod_hi'] = sum(mods) / len(mods)
        # crude rustle centroid: power-weighted centre of the 2-4 k, 4-6 k, 6-20 k bands (geometric centres)
        centres = {'upper_mid': 2828.0, 'presence': 4899.0, 'brilliance': 10954.0}
        pw = [(centres[k], 10 ** (b[k]['avg_db'] / 10)) for k in centres
              if isinstance(b.get(k, {}).get('avg_db'), (int, float))]
        if len(pw) == 3 and sum(w for _, w in pw) > 0:
            out[p + 'rustle_centroid'] = sum(c * w for c, w in pw) / sum(w for _, w in pw)
        bass = b.get('bass', {}).get('avg_db')
        if isinstance(bass, (int, float)) and len(pw) == 3:
            out[p + 'hi_minus_bass'] = 10 * math.log10(sum(w for _, w in pw) / 3) - bass
    elif s == 'bluetooth' and d:
        for sc in d.get('scans') or []:
            if sc.get('kind') != 'ble':
                continue
            # the ids are salted hashes made by the collector; only the share that changed is kept
            ids = {x.get('id') for x in sc.get('devices') or [] if x.get('id')}
            prev = state.get('ble')
            if ids and prev is not None:
                out['ble_new_frac'] = len(ids - prev) / len(ids)
                out['ble_gone_frac'] = len(prev - ids) / len(prev) if prev else 0.0
            state['ble'] = ids
            comp = {}
            for x in sc.get('devices') or []:
                for c in x.get('company_ids') or []:
                    comp[c] = comp.get(c, 0) + 1
            n = sum(comp.values())
            if n:
                out['ble_company_entropy'] = -sum(v / n * math.log(v / n) for v in comp.values())
    elif s == 'wifi' and d:
        ids = {n.get('bssid_h') for n in d.get('networks') or [] if n.get('bssid_h')}
        prev = state.get('wifi')
        if ids and prev is not None:
            out['wifi_new_frac'] = len(ids - prev) / len(ids)
        state['wifi'] = ids
        chans = [n.get('channel') for n in d.get('networks') or [] if isinstance(n.get('channel'), int)]
        if chans:
            out['wifi_5ghz_share'] = sum(1 for c in chans if c > 14) / len(chans)
        out['wifi_hidden'] = sum(1 for n in d.get('networks') or [] if n.get('hidden'))
    elif s == 'system' and d:
        out['sys_fan'] = d.get('fan_rpm')
        out['sys_load1'] = d.get('cpu_load_1m')
        out['sys_net_pkts'] = (d.get('net_packets_sent') or 0) + (d.get('net_packets_recv') or 0)
    elif s == 'radiation' and d:
        out['rad_cps'] = d.get('cps')
    elif s == 'imu' and d and rec.get('valid'):
        out.update(imu_features(d, ctx))
    elif s == 'optical' and d and rec.get('valid'):
        out.update(optical_features(d))
    return _scalars(out)


def imu_features(d, ctx):
    """IMU box per-second summary -> attitude, gait energy, a still flag, magnetic field quality."""
    out = {}
    imus = d.get('imus') or {}
    att = orient.attitude(imus, ctx.imu_cal) if imus else None
    if att:
        out.update(imu_roll=att['roll'], imu_pitch=att['pitch'], imu_g_norm=att['norm'], imu_spread_g=att['spread_g'],
                   imu_rate=_norm(att['rate']), imu_boards=att['n'])
        for f in orient.FACES:
            out['imu_down_' + f] = 1.0 if att['down'] == f else 0.0
    astd = [_norm(v.get('accel_g_std')) for v in imus.values() if v.get('n')]
    gstd = [_norm(v.get('gyro_dps_std')) for v in imus.values() if v.get('n')]
    temps = [v.get('temp_c') for v in imus.values() if isinstance(v.get('temp_c'), (int, float))]
    astd = [x for x in astd if x is not None]
    gstd = [x for x in gstd if x is not None]
    if astd:
        out['imu_astd'] = sum(astd) / len(astd)
    if gstd:
        out['imu_gstd'] = sum(gstd) / len(gstd)
    if astd and gstd:
        out['imu_still'] = 1.0 if out['imu_astd'] < 0.02 and out['imu_gstd'] < 0.5 else 0.0
    if temps:
        out['imu_temp'] = sum(temps) / len(temps)
    out['imu_missed'] = d.get('missed')
    mags = d.get('mags') or {}
    fld = orient.field(mags, att, ctx.mag_cal) if mags else None
    if fld:
        out.update(imu_B_norm=fld['norm'], imu_B_spread=fld['spread'], imu_B_boards=fld['n'],
                   imu_B_clean=1.0 if fld['quality'] == 'clean' else 0.0)
        if fld.get('inclination') is not None:
            out['imu_B_incl'] = fld['inclination']
        if fld.get('heading') is not None:
            h = math.radians(fld['heading'])
            out['imu_head_sin'], out['imu_head_cos'] = math.sin(h), math.cos(h)
    return out


def optical_features(d):
    """Light plate: TSL2591 lux and infrared share, AS7341 band shares (free of gain), LTR390 UV, and any
    temperature / humidity / pressure block present (opt_<block>_<key>)."""
    out = {}
    tsl = d.get('tsl') or {}
    lux = tsl.get('lux')
    if isinstance(lux, (int, float)) and lux >= 0:
        out['opt_loglux'] = math.log10(lux + 0.01)
    if tsl.get('full') and tsl.get('ir') is not None:
        out['opt_ir_share'] = tsl['ir'] / tsl['full']
    out['opt_tsl_sat'] = 1.0 if (d.get('saturated') or tsl.get('sat')) else 0.0
    a = d.get('as7341') or {}
    raw = a.get('raw') or []
    if len(raw) == 8 and sum(raw) > 0:
        tot = float(sum(raw))
        for nm, v in zip(AS7341_BANDS, raw):
            out['opt_f' + nm + '_share'] = v / tot
        out['opt_blue_share'] = (raw[1] + raw[2]) / tot
        out['opt_red_share'] = (raw[6] + raw[7]) / tot
        if a.get('nir') is not None:
            out['opt_nir_share'] = a['nir'] / tot
        g, step, atime = a.get('gain') or 1, (a.get('astep') or 0) + 1, (a.get('atime') or 0) + 1
        if a.get('clear') is not None:
            out['opt_as_logbright'] = math.log10(a['clear'] / (g * step * atime) + 1e-9)
    ltr = d.get('ltr') or {}
    if ltr.get('uvi') is not None:
        out['opt_uvi'] = ltr['uvi']
    if isinstance(ltr.get('lux'), (int, float)) and ltr['lux'] >= 0:
        out['opt_ltr_loglux'] = math.log10(ltr['lux'] + 0.01)
    for blk in ('sht_in', 'sht_ex', 'bmp'):
        for k, v in (d.get(blk) or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out['opt_%s_%s' % (blk, k)] = v
    return out


def record_features(rec, ctx):
    """Every column one record yields."""
    f = base_features(rec)
    f.update(scene_features(rec, ctx))
    return f
