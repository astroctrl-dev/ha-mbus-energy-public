# M-Bus T230 — beta channel

Version 2.7.3-beta.1 is a test candidate, not a stable release. Offline tests and Docker build passed for the candidate code; physical DST validation remains outstanding. The stable app remains on the default branch.

Add this repository in Home Assistant App Store: `https://github.com/astroctrl-dev/ha-mbus-energy-public#beta`. Beta is a separate app with separate local data and settings. Stop the stable app before starting beta; never run both against the same serial adapter or MQTT identities. Back up first. Keep automatic clock synchronization and automatic history off during initial verification. Do not run experimental DST writes without explicit authorization. To roll back, stop beta and restart stable after confirming the meter is in its normal frame.
