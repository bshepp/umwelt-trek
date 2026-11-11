# The code, stage one: from records to a line

*Silicon Dreaming / umwelt-trek.*

This is the part of the project that turns sensor records into the numbers the published lines read, trains
a line, calibrates it and applies it. It is what makes the four models on the Hub usable by someone other
than me. The collector that makes the records is not here yet. It comes in stage two.

| module | what it does |
|---|---|
| `umwelt_trek/features.py` | one sensor record -> named numbers (levels, counts, shares; no identifier, no position, no clock) |
| `umwelt_trek/orient.py` | attitude and magnetic field of a box of IMU boards |
| `umwelt_trek/table.py` | sessions of records -> one row per minute, with labels from `episodes.csv` |
| `umwelt_trek/windows.py` | table columns -> model inputs: the minute, its 10- and 30-minute means, presence flags |
| `umwelt_trek/probe.py` | train one line and score it leave-one-local-day-out |
| `umwelt_trek/calibrate.py` | fit the calibration map; say whether the number is a probability or only a ranking |
| `umwelt_trek/predict.py` | apply a published `model.json` (+ `calib.json`) to a table |
| `examples/make_synthetic.py` | an invented week in the record format, to run all of the above |
| `docs/RECORDS.md` | the record format the table builder reads |

## Try it

```
pip install -r requirements.txt
sh examples/run_example.sh        # invented data -> table -> two lines -> calibration -> prediction
python -m unittest discover tests
```

The example data is made up. Its scores say nothing about the published lines. It shows the formats and
exercises the code.

## Using a published line

```
python -m umwelt_trek.table   --data MY_SESSIONS --out out --episodes my_episodes.csv --tz Europe/Paris
python -m umwelt_trek.predict --table out/scene_minutes.csv --model model.json --calib calib.json --out p.csv
```

`model.json` and `calib.json` are the two files in each model repository. `predict` lays the table's columns
out in the order of the model's `names` and treats an input your table lacks as missing, which the lines
were trained to tolerate. It reports how many inputs were missing.

Be clear about what that buys you. These lines were trained on one laptop, one set of sensors and one
person's days. They are published to show a method and its honest scores, not as detectors that will work
on your hardware. To get a line that means something for you, record your own days in the format of
`docs/RECORDS.md`, write your own `episodes.csv`, and train with `probe`.

The flags that made the four published lines:

| line | command |
|---|---|
| `carrier_C0.03` | `probe --target carrier --C 0.03` |
| `dawn_nolight_C0.03` | `probe --event dawn --exclude sys_,usb_,hue_,light_,opt_ --no-presence --C 0.03` |
| `dawn_hue_C0.03` | `probe --event dawn --exclude sys_,usb_,light_,opt_ --no-presence --C 0.03` |
| `waterfall_np_C0.1` | `probe --event waterfall --exclude sys_,usb_ --dropout 0.5 --no-presence --C 0.1` |

Retraining with these flags on the same table reproduces the binary lines exactly. The four-class `carrier`
line comes out within run-to-run variation of the published one: the same inputs and calibration, weights
equal to about 0.005, accuracy 0.9510 against the published 0.9513. The fit does not settle on identical
weights on every run.

One thing to know when reading a published `model.json` by hand: an input that never varied in training has
`sd` 0 in the `carrier` line's file. Treat a zero `sd` as 1, as `predict` does. Lines trained with this code
write 1 there.

## The rules the code keeps

- **The sensor that would make a label obvious makes the label and is then left out of the inputs.** The
  light makes the dawn label; `--exclude light_,opt_` keeps it from the model. Mains power makes the `desk`
  label; the battery columns are always left out.
- **No clock and no coordinates in the table.** A scene has to be found in the sensors.
- **Whole days are held out.** Minutes within a day are too alike to split at random.
- **Presence is a leak for rare events.** "This sensor was along that day" can predict a walk without
  sensing anything. `--no-presence` drops the flags and `--dropout` teaches a line to live with a missing
  sensor.
- **A line says whether its number can be believed.** After calibration it either beats the constant
  predictor on log-loss or it is a ranking only.

## What stays private, and should for you too

The per-minute table and a line's per-minute output (`beliefs.csv`, `predict --out`) are a diary of the days
they cover: when someone was home, out, asleep. The code writes the table folder with owner-only
permissions. Publish models and scores, not these.

The collection rules, and where the working system still falls short of them, are in
[COLLECTION_POLICY.md](COLLECTION_POLICY.md).

MIT licence.
