# Button and Speed-Preset Settings

[한국어](../ko/buttons-presets.md)

> [!NOTE]
> This is the canonical English user guide maintained with the `carrot-wip` code. When user-visible behavior changes, update this document together with the related code and tests.

This page explains all **15 button and preset settings** from the current implementation, including short/long presses, custom cruise modes, and the conditions under which stock-SCC button messages are sent.

Change these values in **Carrot Web → Settings → Driving control → Buttons and presets**.

> [!CAUTION]
> Button events and stock-SCC messages differ by vehicle. Record the current values and confirm button recognition while safely parked. During a driving test, change only one item and restore normal mode immediately if the result is unexpected.

## Four sections

1. [Button modes](#button-modes)
2. [Speed units](#speed-units)
3. [Button tests and message bursts](#button-spam)
4. [Speed presets](#speed-presets)

## Key behavior to know first

- These functions apply only when the vehicle interface reports the corresponding button event.
- Short and long presses do not share the same increment. A **long press always uses a 10 km/h grid** in the current code.
- In custom modes 1–3, `CruiseSpeedUnit` matters more than `CruiseSpeedUnitBasic`.
- Resume logic can take priority over speed adjustment while cruise is off, ready, stopped, or returning from braking.
- On an mph display, the short-press unit is interpreted as mph and converted internally. The fixed long-press unit remains 10 km/h, about 6.2 mph.

### Why initial values may differ

Carrot Web restores an individual item using the `default` in `carrot_settings.json`, while newly created Params use `params_keys.h` initial values. This branch currently has these differences:

| Parameter | Catalog default | Initial Params value |
|---|---:|---:|
| `PaddleMode` | 1 | 0 |
| `CruiseSpeedUnitBasic` | 10 | 1 |
| `CruiseButtonTest1` / `2` / `3` | 0 / 0 / 0 | 8 / 30 / 1 |
| `CruiseSpeed1` through `5` | 10 / 10 / 10 / 10 / 10 | 30 / 50 / 80 / 110 / 130 |

The button-test catalog default of `0` is even below the displayed minimum. Do not force values to match a table; back up and use the current value on your own device as the baseline.

<a id="button-modes"></a>
## 1. Button modes

### `CruiseButtonMode`

This table describes a short press during normal driving with cruise already active.

On Volkswagen, the separate `SET` button sets the current cluster speed. `RES` restores the saved pre-braking speed when available, otherwise retaining the existing set speed; if no set speed has been initialized, it uses current speed. Existing minimum and maximum set-speed limits still apply.

Separate `SET`/`RES` buttons act once on release, whether tapped or held. The button mode, speed units, and long-press setting below apply to the separate `+`/`-` buttons; when speed comes from stock SCC, the stock set speed takes precedence.

Manual engagement with openpilot longitudinal control is still requested when the physical `SET` or `RES` button is released. The standalone `+`/`-` buttons do not gain an engagement action.

| Value | Short RES/+ | Short SET/- |
|---:|---|---|
| `0` normal | Next `CruiseSpeedUnitBasic` grid point | Previous `CruiseSpeedUnitBasic` grid point |
| `1` custom 1 | Set 30 below 30 km/h, then next `CruiseSpeedUnit` point | Previous `CruiseSpeedUnit` point |
| `2` custom 2 | Same as custom 1 | Match current speed or, under some conditions, enter Carrot cruise |
| `3` custom 3 | First larger value from `CruiseSpeed1` through `5` | Same as custom 2 |

For custom modes 1–3, RES/+ first raises a set speed below 30 km/h to 30. It then searches the grid beginning at 40 km/h with `CruiseSpeedUnit` spacing. Custom mode 3 uses the five presets first and continues on the grid only after the final preset.

SET/- in custom modes 2 and 3 is not a simple subtraction:

- If actual speed is sufficiently above set speed, the set speed can move toward actual speed.
- If actual speed is below set speed, the set speed can be lowered to actual speed.
- If no lower-speed condition applies, the state can enter Carrot cruise.

Use `CruiseButtonMode=0` first if you want predictable grid-based `+/-` behavior.

### `CancelButtonMode`

| Value | Short cancel press |
|---:|---|
| `0` | Cancel cruise while retaining lateral control |
| `1` | Cancel cruise and disengage lateral control |

A **long cancel press always disengages lateral control**, regardless of this mode.

### `LfaButtonMode`

| Value | Short LFA press |
|---:|---|
| `0` normal | Toggle lateral control |
| `1` decelerate-to-stop and ready | Enable the automatic-deceleration/ready flow |
| `2` Carrot cruise | Activate Carrot cruise |

Mode `1` does not immediately command a fixed deceleration. It enables an internal paddle-deceleration waiting state; subsequent stop, lead, and cruise states determine Ready and reactivation behavior. Treat it as experimental because the current code still marks this flow for further work.

A **long LFA press** temporarily toggles the speed condition used by lane mode, independently of `LfaButtonMode`.

### `PaddleMode`

| Value | Current paddle behavior |
|---:|---|
| `0` | No separate paddle action |
| `1` | Cruise off, then Ready |
| `2` | Cruise off, then Ready plus automatic-deceleration state |
| `3` | Activate Carrot cruise |

> [!IMPORTANT]
> The catalog description says `0: cruise ON`, but the running code enters the paddle branch only when `PaddleMode > 0`. On this branch, interpret `0` as **paddle function disabled**.

Vehicles that do not report paddle events will not respond. Left and right paddles currently use the same mode behavior.

### Common long-press behavior

| Button | Long press |
|---|---|
| RES/+ or SET/- | Move repeatedly to the next or previous 10 km/h grid point |
| Following-gap | Cycle `MyDrivingMode`: eco → safe → normal → high speed |
| LFA | Temporarily toggle lane-mode speed application |
| Cancel | Cancel cruise and disengage lateral control |

<a id="speed-units"></a>
## 2. Speed units

| Setting | Range | Actual role |
|---|---:|---|
| `CruiseSpeedUnitBasic` | 1–100 | Normal-mode grid for short RES/SET presses |
| `CruiseSpeedUnit` | 1–100 | Custom-mode grid, SET/- unit, and the unit after the last preset |
| `CruiseButtonLongDelay` | 30–100 | Control frames before RES/SET is considered a long press |

The code rounds to the next grid point rather than simply adding the unit. With normal mode, a unit of 5, and a set speed of 83 km/h, short RES/+ selects 85 and short SET/- selects 80.

### `CruiseButtonLongDelay` is measured in frames

Button processing runs at about 100 Hz:

| Stored value | RES/SET long press | Gap/LFA/cancel long press |
|---:|---:|---:|
| 30 | About 0.30 s | About 0.60 s |
| 40 | About 0.40 s | About 0.70 s |
| 60 | About 0.60 s | About 0.90 s |

Gap, LFA, and cancel add 30 frames internally. Perceived timing can vary with the vehicle's button-message rate.

> [!NOTE]
> Neither speed-unit setting changes the fixed 10 km/h long-press grid.

Recommended order: verify normal mode and `CruiseSpeedUnitBasic=1`, tune only the long-press delay, and then test a custom mode with `CruiseSpeedUnit`.

<a id="button-spam"></a>
## 3. Button tests and message bursts

`CruiseButtonTest1` through `3` do not adjust physical button sensitivity. They control virtual RES/SET messages used to synchronize the set speed of **Hyundai/Kia stock SCC** with the desired speed.

| Setting | Initial Params value | Role |
|---|---:|---|
| `CruiseButtonTest1` | 8 | Consecutive transmissions allowed in one burst |
| `CruiseButtonTest2` | 30 | Rest frames after a burst or driver button input |
| `CruiseButtonTest3` | 1 | Number of message copies for one allowed CAN FD transmission |

The Porter II EV conventional-cruise path uses `CruiseButtonTest1 × 0.01 seconds` as the press duration, clamped to 0.04–0.06 seconds. `CruiseButtonTest2 × 0.01 seconds` is the minimum request interval, with a 0.3-second floor. `CruiseButtonTest3` does not apply to this path. It sends once per fresh stock CLU11 frame, sends two release messages, then waits for the stock set speed to change. After 0.5 seconds without a response, it waits at least 0.5 seconds before retrying. After three consecutive misses it waits at least three seconds and starts a new bounded retry group. A set-speed change in the requested direction resets the miss count. Target fluctuations alone do not interrupt an ongoing press; a stock response or driver intervention can end it early. This does not provide automatic braking, stopping, or headway control.

For Porter conventional cruise, a new button request requires an unrounded target error of at least 1 km/h. This avoids unnecessary tiny requests around a rounding boundary. A full step has no additional debounce delay. Recorded successful vehicle responses took 35–56 ms, so a missing response now times out after 0.5 seconds and retries sooner. The existing pedal, gear, and signal-validity gates remain in force.

Automatic Porter button holds have both an elapsed-time limit of 40–60 ms and a transmission limit of two to three fresh CLU11 frames. Repeated RX samples do not consume this count. This prevents scheduling jitter or floating-point timing from adding a fourth press frame. Two explicit release frames follow a completed hold. This bounds the generated pulse; it does not establish reliable acceptance by the stock ECU. Recorded failures also include three-frame holds.

For Porter conventional cruise, a clear projected following gap and an expired lead deceleration hold allow the target to rise before vehicle speed falls to the lowered stock setting. Request RES+ toward the currently valid planner/navigation target without the extra 0.5s reversal confirmation in this case. Brief opening of a close lead, an active deceleration hold or a lead dropout does not qualify for this immediate reversal. Other deceleration-to-acceleration reversals retain the existing 0.5s confirmation. Valid planner/radar inputs, press/release/response checks, the minimum 0.3s request interval and driver-input/cancel guards still apply. Physical acceleration timing depends on stock acceptance and vehicle control.

If a button request receives no set-speed response within 0.5s, the next request alternates between immediate transmission after a fresh stock CLU11 sample and a 10 ms delayed slot. Three consecutive misses retain the existing three-second backoff. There is still at most one transmission per stock sample; a delayed slot may use the same RX sample on the following control tick. If scheduling cannot provide the delayed slot for 100 ms, it falls back to the default timing. Only a request acknowledged by a stock set-speed change records a preferred slot. Manual input or disabled cruise restores that last acknowledged slot for the same controller session, instead of discarding it. These actions still stop automatic presses, clear the active request and require the existing rearm interval. A failed trial or a physical button press does not overwrite the preferred slot. If there has been no acknowledgement, the default slot is used; restarting the controller clears this memory. Each subsequent miss tries the other timing slot on the next request. Driver cancel and pedal interruption bypass this extra delay. Payloads, counters, pulse limits and retry frequency are unchanged. This is a retry-timing trial for persistent misses, not proof of the stock ECU rejection mechanism or a guaranteed fix. The `PorterButtons` diagnostic records `delay_ms`.

### Porter automatic cancellation below the stock minimum

Carrot Web > Settings > Vehicle & Hardware > Porter Only includes **Porter: cancel cruise below 30 km/h target** (`PorterAutoCancelBelow30`). Default OFF preserves existing button speed matching. ON applies only to Porter II EV with `SpeedFromPCM=0`; changes apply immediately. Valid planner, driver-selected, navigation and existing close-lead targets are checked before the 30 km/h floor. A continuously sub-30 target for 0.3 seconds requests stock cruise cancellation and inhibits resume until stock OFF is observed. Invalid/stale sources and short fluctuations do not start a cancellation. Switching OFF clears this feature's pending request; it does not re-engage cruise.

This uses target speed, not vehicle speed or lead distance alone. Cancellation is a request to release stock cruise, not a brake/stop command. No automatic re-engagement is added. This opt-in function still needs vehicle response validation.

In Settings > Vehicle & Hardware > Porter Only, enable **Porter: dedicated GAP** (`PorterGapUse`) to share `PorterGap1`–`PorterGap4` between the Porter II EV conventional-cruise planner and button deceleration/optional low-target cancellation. Default OFF uses common `TFollowGap1`–`TFollowGap4`. Existing GAP selection buttons remain; switching modes never copies or resets either set of saved values.

Porter GAP1–4 range from 40 to 300 in steps of 5; 50=0.50s. Initial defaults are 100/130/160/200; previously saved dedicated values are preserved. Button decisions use the planner’s applied time after existing speed, driving-mode and deceleration adjustments. Without valid planner time, use the selected mode’s base time. Allow about five seconds for planner refresh after changes.

**Porter: deceleration lookahead** (`PorterLeadReactionTime`) applies to both button deceleration and lead-based low-target cancellation while dedicated GAP is ON. Range 40–80 in steps of 5; 80=8s, 60=6s; initial default 80. Higher values can request deceleration farther away; lower values can wait until closer. Dedicated GAP OFF retains the existing 8s projection. Adjust the dedicated gap and lookahead separately.

The 7m distance floor, existing button/cancel limits and model-stop/navigation targets remain. GAP or lookahead changes do not remove deceleration requested by a model stop judgment. This does not guarantee physical braking, stopping, actual spacing or stock button acceptance.

The confirmed stock cruise set-speed floor on the 2024 Porter II EV is 30 km/h. Steering-wheel button emulation cannot change the stock ECU floor, so the Carrot target, stock set-speed state, button transmission, and panda permission checks use the same 30 km/h minimum. Vehicle speed can fall below 30 km/h while coasting, but stock cruise cannot be set to or hold 29 km/h or less.

With `SpeedFromPCM=0` on Porter, the stock button target uses the lower of the navigation camera approach profile and the longitudinal planner target. A higher terminal planner speed therefore cannot hide the current camera slowdown target. At 30 km/h and above, the cluster set speed follows in 1 km/h steps. A target below the stock floor, such as a 20 km/h limit, can only lower the stock setting to 30 km/h.

Porter vision-lead control uses the selected gap level and the projected distance 8 seconds ahead. When the gap is projected to fall below the selected spacing, it starts lowering the stock set speed toward the lead speed with 1 km/h SET inputs. A radar dropout of up to 0.6 seconds keeps projecting the last lead distance and relative speed. RES+ cannot raise the stock setting until the tracked lead has pulled away continuously for 0.5 seconds, preventing a brief vision-speed fluctuation from restoring the memorized speed. This reduces acceleration from conventional cruise earlier; it cannot command the brakes or guarantee a safe gap, so the driver must brake immediately when the reduction is insufficient.

At roughly 0.01 seconds per control frame, `Test2=30` is about 0.30 seconds. The code may instead use a separate seven-frame wait after detecting that the stock set speed changed.

Scope and exclusions:

- Used for stock-SCC speed synchronization on Hyundai/Kia configurations without openpilot longitudinal control.
- `Test1` and `Test2` can affect both classic CAN and CAN FD button paths.
- `Test3` duplication currently applies to the CAN FD path.
- With `SpeedFromPCM=1`, the RES/SET branch that corrects the difference between desired and stock set speeds does not run.
- `SpeedFromPCM` defaults to `2` (curve/camera deceleration). Restoring its default also uses `2`; updating alone does not change an existing saved value.
- These values do nothing on vehicles that do not use this transmission path.

> [!WARNING]
> Values that are too large can flood button messages or make stock SCC miss inputs. Values that are too small can slow or prevent synchronization. Keep the initial Params values `8 / 30 / 1` if there is no problem.

### Toyota/Lexus stock set speed

With `SpeedFromPCM=3`, stock SET/RES speed becomes Carrot's base target. Mode `1` also uses stock set speed; `0` and `2` retain the existing Carrot speed selection. This setting does not switch between stock ACC and openpilot longitudinal control or enable/disable radar. With openpilot longitudinal control, lead, curve, and camera deceleration can lower the target further.

Mode `0` has one exception: with PCM and openpilot direct longitudinal control on `TOYOTA_RAV4_TSS2_2022`, observed stock set-speed changes and disabled-to-enabled cruise transitions update the base target when CAN is valid. An initially enabled sample only establishes a reference; local button or Bluetooth speed changes take priority in the same cycle. Lower lead, curve, and map targets still apply, and no RES/SET CAN transmission is added.

<a id="speed-presets"></a>
## 4. Speed presets

`CruiseSpeed1` through `CruiseSpeed5` form an ordered table used by short RES/+ presses in `CruiseButtonMode=3`.

| Setting | Initial Params value | Example role |
|---|---:|---|
| `CruiseSpeed1` | 30 | Low-speed/local road |
| `CruiseSpeed2` | 50 | Urban road |
| `CruiseSpeed3` | 80 | Limited-access road |
| `CruiseSpeed4` | 110 | Highway |
| `CruiseSpeed5` | 130 | Final custom step |

These role names are examples, not legal limits or recommended speeds. Use values appropriate for local law and conditions.

The code reads values 1 through 5 and selects the **first one greater than the current set speed**. After all presets, it moves to the next `CruiseSpeedUnit` grid point. Presets are not sorted automatically, so save them in ascending order; duplicates or reversed values may skip steps.

### Special behavior when `CruiseSpeed1=0`

Only preset 1 allows zero. It then becomes a dynamic value based on the current road limit:

- `AutoRoadSpeedLimitOffset >= 0`: road limit + offset
- `AutoRoadSpeedLimitOffset < 0`: road limit × `AutoNaviSpeedSafetyFactor`

For a 60 km/h limit, an offset of 5 produces 65 km/h. An offset of -1 with a 105% safety factor produces 63 km/h. This preset cannot work as expected without valid road-limit input.

Remember that SET/- in custom mode 3 does not walk backward through the preset table.

## Quick troubleshooting

| Symptom | Check first |
|---|---|
| A short press changes speed by more than expected | `CruiseButtonMode`, both speed units |
| Long-press unit differs from the setting | Current code uses a fixed 10 km/h grid |
| Custom mode 3 skips steps | Ascending order and duplicates in presets 1–5 |
| SET/- enters Carrot cruise | This can be normal in custom modes 2 and 3 |
| LFA or paddle does not respond | Whether the vehicle reports that button event |
| Reset produces a surprising value | Difference between catalog default and initial Params value |

## Code references

- Button/preset state machine: `openpilot/selfdrive/car/cruise.py`
- Hyundai/Kia stock-SCC messages: `opendbc_repo/opendbc/car/hyundai/carcontroller.py`
- Catalog ranges/defaults: `openpilot/selfdrive/carrot_settings.json`
- Initial Params values: `openpilot/common/params_keys.h`

[Back to Understanding Settings](settings.md)


### Porter automatic SET from MAIN standby

Settings > Vehicle & Hardware > Porter Only includes **Porter: automatic SET from MAIN standby** (`PorterAutoSetMain`), default OFF. This version requires both host and Panda updates plus a restart for rapid double SET. While parked, turn vehicle MAIN OFF before updating/restarting, then press MAIN ON after boot to establish CRUISE standby. MAIN tracking starts OFF independently of `AutoEngage`; this feature does not require `AutoEngage=2`.

In confirmed MAIN standby with stock cruise OFF, a fresh gas press lasting at least 0.1s and release requests **SET− → release → SET− → release**, regardless of engagement or lateral-control activity. Dashboard and initial target must be 30–160 km/h, with `SpeedFromPCM=0`, drive gear and valid vehicle/planner/radar inputs. Retain the 0.5s MAIN settling. The current double-SET profile requires both front-left and rear-right wheel speeds at 30–160km/h. A dashboard reading above 30 alone cannot start cruise; a below-floor release needs a new pedal cycle after speed rises. Waiting without a pedal cue cannot start cruise.

Each SET is at most three frames/60ms, with about 80ms between the first release and second press. Normal reception completes the sequence in about 0.2s. Panda independently enforces six SET frames total, at least 60ms of release separation and a 240ms envelope. **The second SET− is sent even if the first already engages stock cruise.** It can lower the set speed by one step, so this does not precisely latch speed at pedal release. OEM button messages remain present with an ordinary camera harness; actual vehicle acceptance still needs confirmation.

Brake, CANCEL, MAIN OFF, renewed gas, driver buttons, lost gear/speed/input eligibility or a cancellation request stop the remaining sequence. Automatic cancellation has priority. Ordinary RES+/SET− speed matching cannot interleave with the pair and resumes after it finishes.

Each qualified pedal release permits at most one pair. Failure to engage after both presses does not repeat the same cue. Another pair requires at least three seconds after the last transmission and a fresh qualifying pedal cycle. Retry-blocked or expired releases are discarded rather than executed later. The initial request opportunity lasts at most 0.1s after release; only target recovery within that window can preserve it. Brake/CANCEL also require a fresh pedal cycle while MAIN remains ON.

Automatic SET transmits only on a newly observed CLU11 sample received within 8ms. Remove the extra 10ms delay and timing-slot memory to retain headroom before the next OEM counter. Skip older samples and wait for the next within the existing pedal/press deadlines; waiting never extends their expiry. One TX per sample, two presses/releases, the three-second wait and Panda safety limits remain. `PorterMainSet` reports sample age and late-sample count as `sample_age_ms` and `late_samples`. Actual stock ON feedback still needs confirmation.

Option OFF inhibits new and remaining requests without cancelling already engaged stock cruise. Preserve tracked MAIN state and confirmation history, including physical MAIN changes while disabled. Enabling the option alone cannot start cruise; fresh-pedal authorization is required. Explicit MAIN OFF still blocks.

This feature does not decode absolute OEM MAIN state. Restarting comma while CRUISE standby is already ON can leave an initialization mismatch; use the MAIN-OFF restart sequence or actual stock ON from physical SET to synchronize. TX echo is not ECU acceptance; distinguish stock ON feedback from the `pair_try`/`pair_pending` diagnostics. Older Panda profiles do not permit the rapid second SET.

With below-30 cancellation enabled, a valid low target held for 0.3s prioritizes the existing CANCEL path. CANCEL retains its three-frame/60ms pulse, explicit release and bounded feedback/retry policy. No direct braking, stopping, standstill launch or guarantee of actual SET/CANCEL acceptance is provided.
