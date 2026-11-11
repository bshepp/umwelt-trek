# The records the table builder reads

The collector writes one JSON object per measurement, one per line, into hourly files named
`data_<date>_<hour>.jsonl` inside a session folder. The table builder reads every such file under a
session folder. Anything it does not recognise is skipped, so a session may hold more than this.

Every record has:

| field | meaning |
|---|---|
| `sensor` | which sensor: `system`, `audio_spectrum`, `bluetooth`, `wifi`, `gps`, `radiation`, `spectrum`, `usb_monitor`, `light`, `hue`, `imu`, `optical` |
| `started` or `timestamp` | UTC time of the measurement, ISO 8601 with `Z`. Records are binned by the minute they started |
| `valid` | `true` if the sensor read properly |
| `data` | the measurement, described per sensor below |
| `instance` | which instrument, when a sensor has several: the microphone, the GPS receiver |

What the builder reads from `data`, per sensor. Everything else in a record is ignored.

**system** `cpu_temp_c`, `cpu_percent`, `memory_percent`, `battery_percent`, `battery_plugged_in`, `fan_rpm`,
`cpu_load_1m`, `net_packets_sent`, `net_packets_recv`. The battery fields make the `desk` label and are never
model inputs.

**audio_spectrum** (`instance`: `laptop-mic`, `usb-mic` or `c920-mic`) `rms`, `peak` (linear, full scale 1),
`bands.<band>.avg_db` and `.max_db` for the nine bands `sub_bass, bass, low_mid, mid, upper_mid, presence,
brilliance, high, very_high`, and `features.centroid_hz`, `features.flatness`. The collector reduces sound to
these levels as it arrives. No playable audio is ever written.

**bluetooth** `scans[]`, of which the one with `kind: "ble"` is used: `device_count`, `adverts_per_second`,
`rssi.{median,p25,p75,max}`, `named_devices`, `address_types.{public,random}`, and `devices[]` with `id` (a
salted hash made by the collector) and `company_ids`. The ids are used only to count how many changed since
the previous scan.

**wifi** `network_count` and `networks[]` with `bssid_h` (a salted hash), `rssi`, `channel`, `hidden`.

**gps** (`instance` or `data.device` names the receiver: a name containing `u-blox` or `ttyACM` is the
external one, `FTDI` or `SiRF` the internal one) `mode` (1 none, 2 2D, 3 3D), `satellites_used`, `hdop`,
`speed`, `sats_with_signal`, `peak_signal_dbhz`. The builder reads fix quality only. It never reads a position.

**radiation** `cpm`, `cps`.

**spectrum** `above_baseline_count`, and `strongest_signals[]` with `excess_db` and `internal`.

**usb_monitor** `usb_device_count`.

**light** (a TSL2591 node) `lux`, `full`, `ir`.

**hue** (a webcam reduced to a colour summary; no image is kept) `luma.mean`, `luma.p95`, `cct_k`, `sat`,
`exposure_time`, `gain`, `level`, `clipped.bright`, `colorfulness`.

**optical** (the light plate) `tsl.{lux,full,ir}`, `as7341.{raw[8],clear,nir,gain,astep,atime}`,
`ltr.{uvi,lux}`, `saturated`, and optional `sht_in`, `sht_ex`, `bmp` blocks of plain numbers.

**imu** (a box of several IMU boards, one summary a second) `imus.<channel>.{n, accel_g_mean[3],
accel_g_std[3], gyro_dps_mean[3], gyro_dps_std[3], temp_c}`, `mags.<channel>.{n, mag_gauss_mean[3]}`,
`missed`. The rotations from each board to the box are in `umwelt_trek/orient.py` and are those of my box.

## Episodes

`episodes.csv` holds the things I know and the model has to infer:

```
start_utc,end_utc,labels,note
2030-03-01T08:12Z,2030-03-01T08:47Z,walk;bag-carried,to the shop and back
```

Labels are free words joined by `;`. A minute carries every label of every episode that covers it. The
`carrier` column is derived from them with a small map of which words mean vehicle, carried, at rest or desk
(`--labels-map`, defaults in `table.py`).
