# Collection policy

**Draft, under discussion.** These are the rules the working system follows today,
written down so they can be argued with. Each gives the rule, then the reason.

Where a reason mentions law, it is a layman's summary of United States and California
law, not legal advice, and other places differ. The rules do not depend on it: each
one is meant to hold where the law is silent or looser.

The starting point: *can be received* and *should be kept* are different questions.
Something being lawful to observe in public does not settle what a machine that never
tires, never forgets and can be searched afterwards should store about the people it
passes.

**What this file cannot do.** The code is open and anyone may change it, so nothing here
stops a person who wants to build something else from it. These rules describe what
this project does by default and what changes it will accept. Their use is to the
person who means well and has not thought it through: the defaults do the thinking
first. No machinery is added to the code to police anyone.

## 1. Receive only

The collector listens. It does not connect to, probe, interfere with or transmit
toward anything it does not own.

*Why:* everything else here depends on the collector being a bystander.

## 2. Devices are counted, not identified

WiFi and Bluetooth addresses, and the names of private networks, are replaced by
salted hashes before they reach the disk. The salt stays on the collecting machine.
Names of public hotspots are kept as they are.

*Why:* a network address is broadcast openly and receiving it is lawful. But public
location databases turn a home router's address into a street address, and a phone's
address seen twice is a person seen twice. Privacy law in several places (the GDPR,
California's CCPA) treats such identifiers as personal data for that reason. Counting
the crowd needs none of it.

Only the announcements are read: network name, address, signal strength. The traffic
itself is never captured, encrypted or not. Capturing the contents of someone's
network traffic is interception, not observation.

## 3. Sound is measured, not recorded

Microphones produce levels in frequency bands. No playable audio is stored by the
collector.

A deliberate recording is a separate act, done by hand: one's own voice, animals,
weather, water, an empty trail.

*Why:* conversations are protected in a way appearances are not. California law
(Penal Code 632) forbids recording a confidential conversation without the consent of
everyone in it. "Confidential" turns on what the speakers could reasonably expect, so
a speech to a crowd is not covered and a quiet talk on a park bench may be. A machine
cannot judge that, and a walk passes hundreds of conversations. Loudness and spectrum
describe a place without capturing what anyone said, so the question never arises.

## 4. No image is kept by an always-on sensor

The colour sensor stores a coarse grid of colours, too coarse to show a person. An
object detector stores what kinds of things it saw and how many, not the frame. A
picture is taken only on purpose, and checked for people before it is kept.

Nothing is used to recognise or follow an individual. No faces, no gait, no plates.

*Why:* photographing people in a public place is lawful in the United States, since
nobody there can expect not to be seen. The limits are places where people do expect
privacy (a window into a home, for one), and using someone's likeness to sell
something. But a camera that runs all day and can be searched afterwards is a
different thing from a person taking a photograph, and the law has not caught up with
the difference. The rule here is stricter than the law on purpose.

## 5. Some places have stricter rules, and the machine applies them itself

Inside a place registered as restricted (a workplace, a shared workshop, a political
gathering), only a named short list of sensors runs. Position decides this, not
memory. Inside such a place, a command can make collection stricter and cannot make
it looser.

*Why:* the person carrying the collector is the least reliable part of the policy.

## 6. Broadcasts meant for everyone are kept as broadcast

Aircraft and vessel identifiers are stored as received.

*Why:* they are transmitted so that anyone nearby can know who is there, and United
States law exempts such transmissions from its rules against intercepting radio. They
are also already received everywhere: volunteer and commercial networks log the same
broadcasts worldwide and keep the history. One more receiver in a backpack tells
nobody anything about an aircraft or a ship that is not already on record, so hashing
the identifier would protect no one and would only make the data less useful.

What these records do expose is the collector. The set of aircraft heard at a given
minute is a fingerprint of where the receiver was, so a published list of them
publishes the walk. That falls under rule 7.

Other radio traffic is measured as power in a band and not decoded. Telephone calls,
pagers and anything encrypted are never decoded; listening to those is unlawful as
well as wrong.

## 7. The carrier's own exposure is the carrier's choice, with safe defaults

Rules 1 to 6 protect people who never agreed to be near a sensor, so they cannot be
switched off. This rule protects the person carrying the collector, who can consent,
so it sets defaults and lets them be overridden knowingly.

- **Collection is never thinned.** Position and everything else is recorded in full
  and stays on the collecting machine. Protecting the carrier by recording less would
  cost the data and add failure points, and nothing is exposed until something leaves
  the machine.
- **Protection happens at export.** Data leaves through one export step, and that step
  is private by default: places the carrier has marked (home above all) are cut out,
  with the cut made at an irregular distance so the gap does not point at its centre;
  and the records that give position away without being position are left out unless
  asked for (aircraft heard, named public hotspots, exact times).
- **The carrier may publish more.** Every default can be lifted, one at a time, by
  the person whose track it is.
- **Collected data does not go into a code repository**, private or not. A repository
  can be made public later and its history comes with it.

*Why:* a published coordinate cannot be taken back, and a home address is the one
fact here that can be turned against someone. But whose risk it is matters. A tool
that forbids its user from sharing their own walk is making a choice that belongs to
them; a tool that shares it by accident has made the same mistake the other way.

The export step does not exist yet in the working system; there, nothing is published
at all.

## 8. Odd readings are kept

A position fix kilometres off, a burst of counts, a sensor that disagrees with its
neighbour: flagged, never deleted.

*Why:* this is a different kind of rule from the others. It is about honesty toward
the data rather than toward people, and it is here because the two pull against each
other: the urge to tidy is how a record stops being one.
