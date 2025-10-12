# youtube-fallback service recovery

This document captures the hardened fallback broadcaster script that should be deployed to
`/usr/local/bin/youtube_fallback.sh` together with the associated `EnvironmentFile`
override and sample environment configuration.

The script is designed to be resilient when optional variables are unset, defaults to a
scene duration of 30 seconds and alternates between built-in `lavfi` generators or local
media files depending on the supplied `SCENES_TXT` definition.

See `deploy/youtube_fallback.sh` for the canonical script body that should be installed on
production systems.
