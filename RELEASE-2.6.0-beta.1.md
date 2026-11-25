# M-Bus v2.6.0-beta.1

Opt-in local raw TX/RX JSONL diagnostics for investigating historical measurement dates. No new bus commands. Capture is off after restart; two rotating 5 MiB files retained. Enable capture, observe a normal poll and request monthly history using the existing control, disable capture, wait until queued count is zero, download JSONL. Raw data contains meter IDs and consumption; review before sharing. Existing Excel export unchanged. Physical verification and complete transport coverage remain pending. Stable v2.5.0 is the backup restore target.
