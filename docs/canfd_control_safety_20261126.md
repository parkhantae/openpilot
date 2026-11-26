# CAN-FD control authorization and regression repair

The common CAN-FD suite had 325 failing cases on both upstream and c3-pht.
Forty-two came from obsolete wheel-speed fixture names. Other failures mixed
outdated topology/limit expectations with real authorization defects: torque
violations were ignored, outgoing acceleration could grant its own permission,
and revoked buffered commands could still be delivered.

## Resulting behavior

- Common torque profiles enforce the existing device limits: magnitude 512,
  increase/decrease 10 per request, real-time delta 112, driver torque blending,
  and the 89-valid/two-cut request-bit policy. These values already existed in
  the prior TX checker; the change actually enforces them and removes the
  misleading unused duplicate limits.
- Nonzero acceleration requires current longitudinal permission, including gas
  override and periodic RX-health handling. Sending acceleration or neutral
  SCC mode fields cannot create permission. Without longitudinal control,
  SCC transmission is limited to zero-acceleration cancel messages.
- Only correctly registered RX address/bus/length combinations can update the
  control state. Stock cruise activation requires a rising edge and recent
  driver interaction. MAIN revokes longitudinal permission. This behavior is
  local to CAN-FD; Classic Hyundai/Porter code is unchanged.
- Neutral/CANCEL button requests remain available; active SET/RES/GAP requests
  require permission and cannot grant it. Unknown requests are rejected.
- Permission is checked again before buffered control delivery. CANCEL, brake,
  gas override or RX expiry cannot replay a previous acceleration request.
  Independently permitted lateral control retains its separate conditions.
- Camera-SCC stock longitudinal uses the actual host LFA topology. Non-camera
  HDA2 longitudinal preserves both real host streams, LFA/ECAN and LKAS/ACAN.
  The companion has separate torque, real-time and request-bit history, so
  interleaving streams cannot accumulate another channel's cut authorization.
- Existing angle-mode packet shapes are distinguished by the automatically
  selected CAN-FD-only `CANFD_ANGLE_CONTROL` safety bit (16384). This value is
  separately used by a Classic pedal profile in another safety model. The bit
  does not change the user's selected steering algorithm. It permits only the
  declared angle encodings, checks their activation permission, preserves the
  camera angle mode's disabled LFA torque sentinel, and cannot weaken the
  strict Ioniq torque profile. It does not establish new vehicle-calibrated
  angle/rate limits; angle calibration and road performance remain separate.

The 2022–24 Ioniq 5 HDA2/CameraSCC=2 torque profile remains 8221. Its explicit
fresh-input/independent-lateral checks are retained. Common torque profiles use
the firmware's periodic safety tick for ordinary RX expiry; independent lateral
permission still requires the complete current input set. AutoEngage alone
never supplies longitudinal authorization.

## Test repairs and coverage

The existing 325 failing case IDs are retained and all execute successfully;
none is deleted or newly skipped. The original abstract/base-class skips remain.

- Wheel fixtures encode `WHEEL_SPEED_1` through `WHEEL_SPEED_4` using the same
  CAN-tick scale, instead of silently ignored `WHL_Spd*Val` names.
- Test limits match the existing fork's TX limits, with checks beyond each
  boundary and with controls OFF. Firmware limits are not raised for the tests.
- Explicit expected TX address/bus/DLC tables describe the existing fork's
  additional display/relay messages. Exhaustive unknown-message/bus tests are
  retained and wrong-DLC tests are added. The tests do not read their expected
  whitelist from the live safety configuration.
- Initial forwarding expectations preserve stock traffic until an accepted
  replacement owns an ID; native timeout, FIFO, display and stock-handover
  suites exercise active ownership separately.
- The existing native authorization suite now also exercises common profiles
  with real packed RX data. Queue-only tests explicitly authorize their normal
  stream; separate native tests verify denial, revocation and re-engagement.
- Real production host message builders validate normal camera/stock,
  dual-stream HDA2 and angle-mode packet acceptance, alongside unauthorized
  torque/angle, rate borrowing, request-credit borrowing and cancellation.
- The host CFFI packet includes the firmware struct's trailing alignment bytes.
  Native layout, bitfield and array-stride tests verify the 72-byte packet and
  six-byte payload offset instead of under-allocating 70 bytes.

The common suite, native authorization/layout/channel/FIFO/display suites,
Ioniq interface selection and the repository's full offline signal workflow
were run: 5,372 tests and 365 subtests pass, with 290 pre-existing/abstract
skips and no failures. Within that workflow the common CAN-FD suite passes
699 cases; all 325 original failures are among those passes. The separate
settings Wiki generator suite passes 25 tests.

Machine-readable results and before/after case audits are retained
with the task artifacts. The separate Classic Hyundai suite still has its
143 pre-existing failures with identical IDs before/after this task; they are
outside the common CAN-FD repair and are not claimed fixed.

CI now runs the common suite and layout/channel regressions on c3-pht pushes.
KO/EN setting guides and localized summaries describe authorization and restart
requirements. The fork-only settings Wiki patch is staged, not published to
the upstream Wiki.

## Installation and limits

Update the host and Panda firmware together and restart. The angle-mode safety
bit is derived from the existing vehicle configuration, without a new manual
setting. An old host/new Panda combination can reject undeclared angle frames.

All validation here is offline with native production hooks and synthetic
packets. No live vehicle CAN, Params changes, firmware flash or road validation
was performed. Passing these tests does not diagnose or establish a cure for
previous physical steering/collision warnings, ECU acceptance or driving quality.
