"""Porter EV metric conventional-cruise state, inferred from recorded OEM CAN.

No direct acceleration/brake actuation. Missing/faulted input disables cruise.
"""
import math


def update_porter_state(ret, cp, main_enabled, is_metric):
  ret.cruiseState.nonAdaptive = True
  ret.cruiseState.enabled = False
  ret.cruiseState.available = False
  ret.cruiseState.speed = 0.0
  required = {"E_EMS11": 100_000_000, "TCS13": 100_000_000,
              "ELECT_GEAR": 100_000_000, "TCS15": 300_000_000}
  fresh = bool(cp.can_valid) and is_metric
  for name, max_age in required.items():
    timestamp = max(cp.ts_nanos.get(name, {}).values(), default=0)
    age = cp._last_update_nanos - timestamp
    fresh = fresh and timestamp > 0 and 0 <= age <= max_age
  if not fresh:
    ret.accFaulted = True
    return
  tcs = cp.vl["TCS13"]
  ret.brakePressed = tcs["DriverOverride"] == 2 or tcs["DriverBraking"] == 1
  ret.brakeHoldActive = cp.vl["TCS15"]["AVH_LAMP"] == 2
  ret.parkingBrake = bool(tcs["PBRAKE_ACT"])
  ret.brakeLights = bool(tcs["BrakeLight"] or ret.brakePressed)
  target = cp.vl["E_EMS11"]["Cruise_Limit_Target"]
  valid_target = math.isfinite(target) and (target == 0 or 30 <= target <= 160)
  ret.accFaulted = tcs["ACCEnable"] != 0 or not valid_target
  if ret.accFaulted:
    return
  active = target > 0 and not (ret.brakePressed or ret.brakeHoldActive or ret.parkingBrake)
  ret.cruiseState.available = bool(main_enabled or active)
  ret.cruiseState.enabled = active
  ret.cruiseState.speed = target / 3.6 if active else 0.0


def supports_porter_button_cruise(CP):
  return (CP.brand == "hyundai" and CP.carFingerprint == "HYUNDAI_PORTER_II_EV" and
          CP.pcmCruise and not CP.openpilotLongitudinalControl and
          any(str(config.safetyModel) == "hyundai" and config.safetyParam == 1025 for config in CP.safetyConfigs))
