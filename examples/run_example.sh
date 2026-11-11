#!/bin/sh
# The whole pipeline on invented data: records -> per-minute table -> two lines -> calibration -> prediction.
# Run from the repository root:   sh examples/run_example.sh
set -e
PY=${PYTHON:-python3}
W=${WORK:-example_data}

$PY examples/make_synthetic.py --out "$W" --days 6
$PY -m umwelt_trek.table --data "$W/sessions" --out "$W/out" --episodes "$W/episodes.csv"

# carrier: desk / carried / vehicle, from everything except the mains-power columns
$PY -m umwelt_trek.probe --csv "$W/out/scene_minutes.csv" --zoo "$W/out/zoo" --target carrier

# dawn without any light sensor: the plate makes the label and is then left out of the inputs
$PY -m umwelt_trek.probe --csv "$W/out/scene_minutes.csv" --zoo "$W/out/zoo" --event dawn \
    --exclude sys_,usb_,light_,opt_ --no-presence --name dawn_nolight

for line in carrier dawn_nolight; do
    pk=$(ls -d "$W/out/zoo/$line"/* | tail -1)
    $PY -m umwelt_trek.calibrate "$pk"
done

pk=$(ls -d "$W/out/zoo/dawn_nolight"/* | tail -1)
$PY -m umwelt_trek.predict --table "$W/out/scene_minutes.csv" --model "$pk/model.json" --calib "$pk/calib.json" \
    --out "$W/out/dawn_p.csv"
echo "done: $W/out"
