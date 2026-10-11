# Collection policy

**Draft, under discussion.** These are the rules the working system follows today,
written down so they can be argued with. Each gives the rule, then the reason.

The starting point: *can be received* and *should be kept* are different questions.
Something being lawful to observe in public does not settle what a machine that never
tires, never forgets and can be searched afterwards should store about the people it
passes.

## 1. Receive only

The collector listens. It does not connect to, probe, interfere with or transmit
toward anything it does not own.

*Why:* everything else here depends on the collector being a bystander.

## 2. Devices are counted, not identified

WiFi and Bluetooth addresses, and the names of private networks, are replaced by
salted hashes before they reach the disk. The salt stays on the collecting machine.
Names of public hotspots are kept as they are.

*Why:* a network address is broadcast openly, but a database lookup turns a home
router's address into a street address, and a phone's address seen twice is a person
seen twice. Counting the crowd needs neither.

## 3. Sound is measured, not recorded

Microphones produce levels in frequency bands. No playable audio is stored by the
collector.

A deliberate recording is a separate act, done by hand: one's own voice, animals,
weather, water, an empty trail.

*Why:* conversations are protected in a way appearances are not. In many places,
California among them, recording a conversation needs the consent of everyone in it.
Loudness and spectrum describe a place without capturing what anyone said.

## 4. No image is kept by an always-on sensor

The colour sensor stores a coarse grid of colours, too coarse to show a person. An
object detector stores what kinds of things it saw and how many, not the frame. A
picture is taken only on purpose, and checked for people before it is kept.

Nothing is used to recognise or follow an individual. No faces, no gait, no plates.

*Why:* photographing a public place is ordinary. A camera that runs all day and can
be searched afterwards is a different thing from a person taking a photograph.

## 5. Some places have stricter rules, and the machine applies them itself

Inside a place registered as restricted (a workplace, a shared workshop, a political
gathering), only a named short list of sensors runs. Position decides this, not
memory. Inside such a place, a command can make collection stricter and cannot make
it looser.

*Why:* the person carrying the collector is the least reliable part of the policy.

## 6. Broadcasts meant for everyone are kept as broadcast

Aircraft and vessel identifiers are stored as received.

*Why:* they are transmitted so that anyone nearby can know who is there. This is the
one place where the identifier is the point of the signal. Open to argument.

## 7. The collector's own track is the most sensitive thing it makes

Position is recorded in full and never published raw. Where the carrier lives is not
published at any precision. Collected data does not go into a code repository.

*Why:* a published coordinate cannot be taken back.

## 8. Odd readings are kept

A position fix kilometres off, a burst of counts, a sensor that disagrees with its
neighbour: flagged, never deleted.

*Why:* this is a different kind of rule from the others. It is about honesty toward
the data rather than toward people, and it is here because the two pull against each
other: the urge to tidy is how a record stops being one.
