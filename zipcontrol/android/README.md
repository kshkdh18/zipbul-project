# Device guard

`uv run --frozen python android/build.py` extracts a SHA-256 pinned scrcpy 4.1 source archive,
applies exact-match patches, compiles `Guard.java` with Android SDK 36 and Java 17, then runs d8.
The upstream commit, source checksum, patch/build-script checksum and binary checksum are recorded
in `artifacts/android/manifest.json`. The system scrcpy installation is not modified.

The fork rejects ordinary scrcpy input messages. Its control channel accepts type **200**, followed
by a big-endian 32-bit UTF-8 JSON length (1–8192 bytes) and the JSON body. Device replies use the
same envelope and identify `protocol=jipbul-guard-4`.

Operations: `hello`, `arm`, `command`, `manual_command`, `update`, `heartbeat`, `release`, `stop`. Every request has a
`request_id`; asynchronous device events use zero. Arm binds two calibrated circles, a video epoch,
and the foreground package (`dji.go.v5`, or Chrome only for diagnostic tests). Commands have a
strictly increasing `command_id` and two vectors/null. AI `command` permits the full radius and a 100–2000ms device-clock lifetime. The Mac mission executor converts model directions to the operator-selected radius before sending; the server receives final normalized positions. Operator-only `manual_command` also permits the full radius and a 100–500ms lifetime; the GUI renews it only while the actual button remains pressed. Both paths share the watchdog and release logic. Updates
perform interpolation only. Heartbeats renew the 300ms link lease only.

All injection, expiry, release and geometry transitions serialize on the guard monitor. A separate
thread probes the foreground package/keyguard so a slow Binder query cannot hold the injection lock.
The expiry thread also rejects foreground observations older than 300ms. Release failure is latched;
the server reports injection state, never aircraft motion or physical stopping.

The guarded process is launched with `setsid` and `nohup`, with a private device log. A host-side ADB
shell waits for it, while the device process is isolated from that shell's hangup/process group.
Cleanup checks the process command line for both its class and unique SCID before terminating it.
Hard-killing the Android process itself is outside the release guarantee. USB behavior must be
validated on the actual device; see the project validation record.

The original Apache-2.0 license is copied to `artifacts/android/SCRCPY-LICENSE` during the build.
