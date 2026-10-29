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

After an automatic SET- request, switching back to RES+ requires a target at least 1 km/h above the stock setting continuously for 0.5 seconds. A lower target restarts confirmation; pedal/invalid-input or observation gaps also restart it. This confirmation runs during the normal release/response interval. Further SET- requests, initial acceleration and subsequent RES+ steps keep their existing timing. Manual input or cruise disable clears the reversal state. This reduces immediate acceleration reversals after brief target changes; it does not filter radar detections or provide direct braking.

If three consecutive button requests receive no set-speed response, the existing three-second backoff also alternates the next retry group between immediate transmission after a fresh stock CLU11 sample and a 10 ms delayed slot. There is still at most one transmission per stock sample; a delayed slot may use the same RX sample on the following control tick. If scheduling cannot provide the delayed slot for 100 ms, it falls back to the default timing. Only a request acknowledged by a stock set-speed change records a preferred slot. Manual input or disabled cruise restores that last acknowledged slot for the same controller session, instead of discarding it. These actions still stop automatic presses, clear the active request and require the existing rearm interval. A failed trial or a physical button press does not overwrite the preferred slot. If there has been no acknowledgement, the default slot is used; restarting the controller clears this memory. Subsequent consecutive misses can still alternate timing. Driver cancel and pedal interruption bypass this extra delay. Payloads, counters, pulse limits and retry frequency are unchanged. This is a retry-timing trial for persistent misses, not proof of the stock ECU rejection mechanism or a guaranteed fix. The `PorterButtons` diagnostic records `delay_ms`.

### Porter automatic cancellation below the stock minimum

Carrot Web > Settings > Vehicle & Hardware > Porter Only includes **Porter: cancel cruise below 30 km/h target** (`PorterAutoCancelBelow30`). Default OFF preserves existing button speed matching. ON applies only to Porter II EV with `SpeedFromPCM=0`; changes apply immediately. Valid planner, driver-selected, navigation and existing close-lead targets are checked before the 30 km/h floor. A continuously sub-30 target for 0.3 seconds requests stock cruise cancellation and inhibits resume until stock OFF is observed. Invalid/stale sources and short fluctuations do not start a cancellation. Switching OFF clears this feature's pending request; it does not re-engage cruise.

This uses target speed, not vehicle speed or lead distance alone. Cancellation is a request to release stock cruise, not a brake/stop command. No automatic re-engagement is added. This opt-in function still needs vehicle response validation.

Use `PorterGap1`–`PorterGap4` in Porter Only to configure each gap level’s lead-button deceleration threshold. Defaults are 100/130/160/200 (1.0/1.3/1.6/2.0 seconds), range 0–300, step 5 (0.05s). Higher values constrain the target at a greater distance. Changes immediately affect both the button target and the lead check for optional below-30 cancellation. The distance threshold is max(7m, 5m + ego speed × configured time); this does not guarantee actual following distance or braking. Web TF1–TF4 remain separate planner settings. The level-count setting does not apply to stock longitudinal control.

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

Settings > Vehicle & Hardware > Porter Only includes **Porter: automatic SET from MAIN standby** (`PorterAutoSetMain`), default OFF. After turning ON, restart to apply the dedicated Panda configuration, then physically operate MAIN. The synthetic startup ON value from `AutoEngage=2` is not authorization. Turning OFF immediately inhibits new requests but does not cancel already engaged stock cruise.

Engagement or active lateral control, `SpeedFromPCM=0`, target and actual speeds of 30–160 km/h, and valid planner/radar signals are required. After 0.5 seconds of continuous conditions, request a short SET−, never RES+. While stock cruise is OFF, pulses are limited to three frames/60ms, at least one second apart, with a three-second wait after three attempts. Gas inhibits requests and restarts confirmation. Observation gaps, brake, hold, parking brake, CANCEL, MAIN OFF or setting OFF revoke authorization. Clear the blocking condition and cycle MAIN OFF then ON to rearm.

With below-30 automatic cancellation enabled too, that cancellation retains MAIN authorization so the same conditions can restart through SET−. Actual speed below 30 km/h prevents restart; the driver must accelerate. No direct braking, stopping, guaranteed following distance or launch from standstill is provided. SET starts stock cruise at the current driving speed; existing button control subsequently matches the target. Vehicle acceptance of this automatic SET path has not been validated.


Stock cruise OFF may clear engagement while lateral control remains active. In that case, SET still requires physical MAIN authorization and every other guard. Actual stock engagement synchronizes only the MAIN tracking state; it cannot restore authorization revoked by brake or CANCEL. Delayed ON feedback immediately after MAIN OFF is not used to rearm.

Cancellation uses at most three frames/60ms of CANCEL followed by explicit release. Without confirmed OFF, wait 0.5 seconds after release and retry; after three requests wait three seconds. Start with the acknowledged transmission slot, then alternate 0/10ms on missing feedback. Cancellation excludes SET/RES and driver buttons take priority. TX echo alone is not success. Vehicle acceptance of this correction’s CANCEL/SET remains unvalidated.

Porter GAP values 0–99 are stored and applied too. 50 means 0.5s; 0 removes only the time term, retaining the existing 7m minimum distance threshold. Levels remain independent without automatic sorting.

In MAIN-authorized standby, accelerate to at least 30 km/h and release gas: with valid target/actual speed conditions, request SET− after 0.1s of release confirmation. The minimum 0.5s since MAIN authorization and existing retry intervals remain. Stock SET engages at the actual speed when accepted, so it cannot lock the exact pedal-release instant’s speed. Existing target-speed matching continues afterward. Brake, CANCEL, invalid inputs and sub-30 targets are not bypassed.
