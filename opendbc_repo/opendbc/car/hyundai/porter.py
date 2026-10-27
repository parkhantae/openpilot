"""Porter EV metric conventional-cruise state, inferred from recorded OEM CAN.

No direct acceleration/brake actuation. Missing/faulted input disables cruise.
"""
import math

# Confirmed on the 2024 Porter II EV: the conventional-cruise ECU accepts
# SET- down to 30 km/h and does not expose a lower set speed. Button emulation
# cannot override that ECU limit.
PORTER_CRUISE_MIN_KPH = 30
PORTER_CRUISE_MAX_KPH = 160
PORTER_LEAD_REACTION_S = 1.5
PORTER_GAP_TIME_S = (1.0, 1.3, 1.6, 2.0)


def pcm_cruise_min_kph(CP):
  return PORTER_CRUISE_MIN_KPH if CP.brand == "hyundai" and CP.carFingerprint == "HYUNDAI_PORTER_II_EV" else 30


def porter_navi_target_kph(planner_target_kph, navi_target_kph):
  """Apply the current navigation cap to the stock-cruise button target."""
  if not math.isfinite(planner_target_kph):
    return planner_target_kph
  if math.isfinite(navi_target_kph) and 0 < navi_target_kph <= 250:
    planner_target_kph = min(planner_target_kph, navi_target_kph)
  return max(PORTER_CRUISE_MIN_KPH, planner_target_kph)


def porter_lead_target_kph(target_kph, ego_speed, lead_distance, lead_relative_speed, gap_level, *, lead_visible=True):
  """Lower the conventional-cruise button target before a closing lead reaches the selected gap."""
  values = (target_kph, ego_speed, lead_distance, lead_relative_speed)
  if not lead_visible or not all(math.isfinite(v) for v in values) or ego_speed < 0 or lead_distance <= 0:
    return target_kph
  if lead_relative_speed > 0.2:
    return target_kph

  gap_index = min(len(PORTER_GAP_TIME_S), max(1, int(gap_level or 2))) - 1
  desired_distance = max(7.0, 5.0 + ego_speed * PORTER_GAP_TIME_S[gap_index])
  projected_distance = lead_distance + min(0.0, lead_relative_speed) * PORTER_LEAD_REACTION_S
  if projected_distance >= desired_distance:
    return target_kph

  lead_speed_kph = max(0.0, ego_speed + lead_relative_speed) * 3.6
  return max(PORTER_CRUISE_MIN_KPH, min(target_kph, lead_speed_kph))


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
  valid_target = math.isfinite(target) and (target == 0 or PORTER_CRUISE_MIN_KPH <= target <= PORTER_CRUISE_MAX_KPH)
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


class PorterCruiseButtons:
  """One bounded press/release, then wait for fresh OEM set-speed feedback.

  None means no frame; 0 is an explicit release. Missing acknowledgements use
  bounded retry groups separated by a quiet period. The timing follows observed
  short OEM presses, not a vehicle acceptance claim.
  """
  def __init__(self):
    self.phase = "idle"
    self.status = "inactive"
    self.last_frame = None
    self.last_time = None
    self.next_request = 0.0
    self.direction = 0
    self.baseline = 0
    self.started = 0.0
    self.hold = 0.12
    self.release_count = 0
    self.acknowledged = False
    self.fault = False
    self.cancel_seen = False
    self.requests = 0
    self.acks = 0
    self.timeouts = 0
    self.consecutive_timeouts = 0
    self.max_consecutive_timeouts = 3
    self.ack_timeout = 0.5
    self.retry_backoff = 3.0

  def update(self, now, target, current, frame_key, *, enabled, blocked=False,
             manual=False, cancel=False, press_seconds=0.08, gap_seconds=0.3):
    had_press = self.phase == "press"
    fresh = frame_key is not None and frame_key != self.last_frame
    if fresh:
      self.last_frame = frame_key
    if not math.isfinite(now) or (self.last_time is not None and now < self.last_time):
      self.fault = True
      self.phase = "idle"
      self.status = "clock_fault"
      return 0 if had_press and fresh and not manual else None
    self.last_time = now
    if manual:
      self.phase = "idle"
      self.fault = False
      self.consecutive_timeouts = 0
      self.cancel_seen = False
      self.next_request = now + 0.3
      self.status = "manual"
      return None
    if cancel:
      self.phase = "idle"
      self.status = "cancel"
      if fresh and not self.cancel_seen:
        self.cancel_seen = True
        return 4
      return None
    self.cancel_seen = False
    if not enabled:
      self.phase = "idle"
      self.fault = False
      self.consecutive_timeouts = 0
      self.next_request = now + 0.3
      self.status = "inactive"
      return 0 if had_press and fresh else None
    finite = all(math.isfinite(v) for v in (target, current, press_seconds, gap_seconds))
    requested_target = target
    if finite:
      target, current = int(target + 0.5), int(current + 0.5)
    valid = (finite and
             PORTER_CRUISE_MIN_KPH <= target <= PORTER_CRUISE_MAX_KPH and
             PORTER_CRUISE_MIN_KPH <= current <= PORTER_CRUISE_MAX_KPH and
             press_seconds > 0 and gap_seconds >= 0)
    if blocked or not valid or frame_key is None:
      self.phase = "idle"
      self.next_request = now + 0.3
      self.status = "blocked" if valid else "invalid_input"
      return 0 if had_press and fresh else None
    if self.fault:
      self.status = "fault"
      return None
    if self.phase != "idle":
      change = current - self.baseline
      if change and change * self.direction < 0:
        self.fault = True
        self.phase = "idle"
        self.status = "wrong_direction"
        return 0 if had_press and fresh else None
      if change * self.direction > 0:
        if not self.acknowledged:
          self.acks += 1
          self.consecutive_timeouts = 0
        self.acknowledged = True
      if now - self.started >= self.ack_timeout and not self.acknowledged:
        self.phase = "idle"
        self.timeouts += 1
        self.consecutive_timeouts += 1
        if self.consecutive_timeouts >= self.max_consecutive_timeouts:
          # A temporary ECU miss must not disable speed matching for the rest
          # of the drive. Keep each attempt bounded, then retry a new group
          # after a longer quiet period.
          self.consecutive_timeouts = 0
          self.next_request = now + max(self.retry_backoff, gap_seconds)
          self.status = "retry_backoff"
        else:
          # The conventional-cruise ECU can occasionally miss a complete
          # pulse. Retry after a bounded quiet period, then latch after three
          # consecutive misses before entering the longer retry backoff.
          self.next_request = now + max(0.5, gap_seconds)
          self.status = "retry_wait"
        return 0 if had_press and fresh else None
      if self.phase == "press" and (self.acknowledged or now - self.started >= self.hold):
        self.phase = "release"
        self.release_count = 0
      if self.phase == "release":
        self.status = "release"
        if fresh:
          self.release_count += 1
          if self.release_count >= 2:
            self.phase = "wait"
          return 0
        return None
      if self.phase == "wait":
        self.status = "acknowledged" if self.acknowledged else "waiting_ack"
        if not self.acknowledged or now < self.next_request:
          return None
        self.phase = "idle"
    if self.phase == "idle":
      # OEM set speed is integral, while the planner target changes continuously.
      # Rounding a 0.5 km/h error used to start a pulse that the next planner
      # update could cancel before the ECU registered it, then latch no_ack.
      # Only start a complete step once the unrounded error reaches 1 km/h.
      at_target = abs(requested_target - current) < 1.0 - 1e-5
      if at_target or now < self.next_request:
        self.status = "at_target" if at_target else "cooldown"
        return None
      if not fresh:
        self.status = "waiting_frame"
        return None
      self.direction = 1 if target > current else -1
      self.baseline = current
      self.started = now
      self.hold = min(0.15, max(0.12, press_seconds))
      self.next_request = now + max(0.3, gap_seconds)
      self.acknowledged = False
      self.phase = "press"
      self.requests += 1
    self.status = "press"
    return (1 if self.direction > 0 else 2) if fresh else None
