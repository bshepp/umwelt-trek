# umwelt-trek

A multi-sensor field collector that runs on a laptop in a backpack. It records what
its sensors meet on a walk: position, radio spectrum, radiation, light, sound levels,
and how many radios are nearby. It also carries rules for what it should record, which
are narrower than what it can.

*Umwelt*: the world as a particular creature's senses present it.

## Status

**Nothing is released here yet.** The collector exists and is used daily, in a private
working repository whose history cannot be published (it contains places). This
repository is where a scrubbed copy of the code will go. Until it does, this page
describes the tool; it is not the tool.

## What it is

- **One worker per sensor.** Each sensor is a plugin with its own pace, from once a
  second to once a minute. A slow or failing sensor is set aside for a while and does
  not hold up the others.
- **Plain files.** Records are JSON lines, one per reading. No database is needed to
  collect or to read.
- **Any USB port.** Devices are found by what they are, never by where they are
  plugged in.
- **A policy between the sensors and the disk.** See below.

Sensors in use on the working system:

| Sensor | Hardware | What is kept |
|---|---|---|
| Position | two GPS receivers | every fix from each receiver, outliers included |
| Spectrum | HackRF One | a power sweep, 1 MHz to 6 GHz, once a minute |
| Aircraft | RTL-SDR with a 1090 MHz filter | aircraft heard, as broadcast |
| Radiation | Geiger counter | counts every second |
| Light | TSL2591 on a microcontroller | visible and infrared, every second |
| Sound | microphones | level in frequency bands; no playable audio |
| WiFi, Bluetooth | the laptop's radios | counts and signal strengths; identifiers only as salted hashes |
| Colour | webcam | a coarse colour summary; no image |
| Laptop | internal | battery, temperature, load |

A vessel (AIS) receiver, an RTL-SDR dongle with AIS-catcher, received its first ships
on 2026-10-11.

## What it should collect

A sensor platform can record far more than it ought to. The working system treats
that as a design problem: the rules are in the code path, between the sensor and the
disk, so that following them does not depend on remembering to.

The rules, and the reasoning behind each, are in
[COLLECTION_POLICY.md](COLLECTION_POLICY.md). That file is a draft.

## What it is for

The current question is whether a small model can tell that the sun is rising from
sensors that do not make it obvious, such as a radio spectrum sweep, with the light
sensor present only to label the data. Data is being collected. **No model has been
trained, and there is no result.**

## License

MIT. See [LICENSE](LICENSE).
