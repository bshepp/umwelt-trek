# umwelt-trek

Part of **Silicon Dreaming**.

A multi-sensor field collector that runs on a laptop in a backpack, and the models
trained on what it records. It records what its sensors meet on a walk: position,
radio spectrum, radiation, light and colour, sound levels, motion, and how many radios
are nearby. It also carries rules for what it should record, which are narrower than
what it can.

*Umwelt*: the world as a particular creature's senses present it.

## Status

**The code is not released here yet.** The collector exists and is used daily, in a
private working repository whose history cannot be published (it contains places).
This repository is where a scrubbed copy of the code will go. Until it does, this page
describes the tool; it is not the tool.

**Models are released.** The first scene lines are published on Hugging Face (below),
with cards that say exactly what each one can and cannot do.

## What it is

- **One worker per sensor.** Each sensor is a plugin with its own pace, from once a
  second to once a minute. A slow or failing sensor is set aside for a while and does
  not hold up the others; a device that is plugged back in is picked up at once.
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
| Vessels | RTL-SDR, AIS | ships heard, as broadcast |
| Small radio devices | RTL-SDR at 315 / 433 MHz; a Flipper Zero, receive-only | kinds and counts; device numbers and codes as salted hashes |
| Radiation | Geiger counter | counts every second |
| Light | TSL2591 on a microcontroller | visible and infrared, every second |
| Colour and UV | a light plate: TSL2591, AS7341 (eight visible bands), LTR390 (UV) | band strengths and UV index, every second |
| Motion and attitude | an IMU box: several accelerometer / gyroscope / magnetometer boards on a microcontroller | orientation, gait energy, stillness, field strength |
| Sound | microphones | level in frequency bands; no playable audio |
| WiFi, Bluetooth | the laptop's radios | counts and signal strengths; identifiers only as salted hashes |
| Colour (camera) | webcam | a coarse colour summary; no image |
| Laptop | internal | battery, temperature, load |
| Weather | a public archive of airport weather reports, downloaded daily | used as labels only, never as a model input |

## What it should collect

A sensor platform can record far more than it ought to. The working system treats
that as a design problem: the rules are in the code path, between the sensor and the
disk, so that following them does not depend on remembering to.

The rules, and the reasoning behind each, are in
[COLLECTION_POLICY.md](COLLECTION_POLICY.md). That file is a draft, and it now also
says where the working system falls short of it.

## What it is for

The question is whether a small model can name the scene the collector is in, from
sensors that do not make it obvious: is the laptop on a desk, carried, set down in a
bag, in a vehicle; is the sun rising; is this the walk past the waterfall; is this
under trees. The sensor that would make a label obvious (a light sensor for the
dawn) is used only to label the data, never as an input.

Every minute of recording becomes one row of features. A line is a small model
trained on those rows for one question, scored on days it never saw, calibrated
afterwards so that its probability means what it says, and kept in a zoo with its
lineage. Lines will be crossed and selected, the way plant lines are.

### Results so far (2026-11-06)

Honest numbers, on held-out days, against the obvious baseline:

- **Carrier** (desk / carried / set down / vehicle): accuracy 0.95 against a majority
  rate of 0.93; carried precision and recall 0.81 / 0.83. The first line whose
  probabilities beat the constant predictor after calibration. Set-down and vehicle
  are not yet separated from the desk by any sensor in the set; a bag-flap switch is
  next.
- **Dawn without any light sensor**: ranks minutes by dawn-likeness with AUC 0.71 from
  microphones, radio counts and GPS quality alone; 0.82 when the webcam's colour
  summary is allowed. Ten dawns so far. The probabilities are not yet trustworthy,
  only the ranking.
- **Waterfall**: AUC 0.83, six of eight passes called; the microphone inside the bag
  cannot hear the falls, so this is mostly the radio quiet of the park.
- **Under trees**: nothing yet; six episodes.

## Models

Published on Hugging Face under the Silicon Dreaming name, one repository per line,
each with its weights, its calibration map and a card: the held-out scores, whether
the number can be believed or only the ranking, and how the data was handled.

- `bshepp/umwelt-trek-carrier_C0.03`
- `bshepp/umwelt-trek-waterfall_np_C0.1`
- `bshepp/umwelt-trek-dawn_hue_C0.03`
- `bshepp/umwelt-trek-dawn_nolight_C0.03`

The models are the exact packets from the working zoo, with their wrapping stripped.
What never leaves the collecting machine: the per-minute table they were trained on,
and their per-minute outputs, which are the carrier's days. The feature extractor
that makes a packet usable follows with the code.

One dataset is public, and it is not about bystanders: the
[cat keyboard corpus](https://huggingface.co/datasets/bshepp/cat-keyboard-corpus), the
messages the two cats of the house have typed into the working session.

## License

Code: MIT, see [LICENSE](LICENSE). Published models and their cards: CC BY 4.0.
