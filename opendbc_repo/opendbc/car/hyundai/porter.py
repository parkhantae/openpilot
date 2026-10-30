"""Porter EV metric conventional-cruise state, inferred from recorded OEM CAN.

No direct acceleration/brake actuation. Missing/faulted input disables cruise.
"""
import math

# Confirmed on the 2024 Porter II EV: the conventional-cruise ECU accepts
# SET- down to 30 km/h and does not expose a lower set speed. Button emulation
# cannot override that ECU limit.
PORTER_CRUISE_MIN_KPH = 30
PORTER_CRUISE_MAX_KPH = 160
PORTER_LEAD_REACTION_S = 8.0
PORTER_LEAD_HOLD_S = 0.6
PORTER_LEAD_OPENING_CONFIRM_S = 0.5
PORTER_BUTTON_ACCEL_CONFIRM_S = 0.5
PORTER_GAP_TIME_S = (1.0, 1.3, 1.6, 2.0)
PORTER_PLANNER_GAP_TIME_S = (1.1, 1.2, 1.4, 1.6)


def porter_gap_time_s(params, gap_level, planner_time_s=None):
  """Use the fresh planner's applied TF, or its selected base setting."""
  if planner_time_s is not None and math.isfinite(planner_time_s) and .3 <= planner_time_s <= 30:
    return planner_time_s
  index = min(4, max(1, int(gap_level or 2))) - 1
  try:
    key = f"TFollowGap{index + 1}"
    if hasattr(params, "get") and params.get(key) is None:
      return PORTER_PLANNER_GAP_TIME_S[index]
    value = params.get_int(key)
  except (KeyError, TypeError, ValueError):
    return PORTER_PLANNER_GAP_TIME_S[index]
  return value * 0.01 if 40 <= value <= 300 else PORTER_PLANNER_GAP_TIME_S[index]


def porter_steer_request_frames(configured_frames):
  # Hyundai's native safety requires 89 matching requests before another
  # nonzero-torque request-bit cut. A lower user setting resets safety's
  # torque history on rejection, so subsequent commands can remain blocked.
  return max(89, configured_frames)


def pcm_cruise_min_kph(CP):
  return PORTER_CRUISE_MIN_KPH if CP.brand == "hyundai" and CP.carFingerprint == "HYUNDAI_PORTER_II_EV" else 30


def porter_auto_set_speed_valid(CP, CS):
  """Versioned dashboard-speed eligibility with independent wheel plausibility."""
  if not any(c.safetyParam in (11265, 60417) for c in getattr(CP, "safetyConfigs", ())):
    return math.isfinite(CS.vEgo) and 30 <= CS.vEgo * 3.6 <= 160
  cluster = getattr(CS, "vEgoCluster", float("nan")) * 3.6
  wheels = getattr(CS, "wheelSpeeds", None)
  fl = getattr(wheels, "fl", float("nan")) * 3.6
  rr = getattr(wheels, "rr", float("nan")) * 3.6
  # Both wheels at >=30 already satisfy the original admission floor. Use
  # dashboard/wheel agreement only to qualify the added 25..<30 range;
  # deceleration-related dashboard lag must not revoke the original range.
  return (all(math.isfinite(v) for v in (cluster, fl, rr)) and
          30 - 1e-5 <= cluster <= 160 + 1e-5 and 25 - 1e-5 <= fl <= 160 + 1e-5 and 25 - 1e-5 <= rr <= 160 + 1e-5 and
          ((fl >= 30 - 1e-5 and rr >= 30 - 1e-5) or
           (abs(cluster - fl) <= 5 + 1e-5 and abs(cluster - rr) <= 5 + 1e-5)))


def porter_navi_target_kph(planner_target_kph, navi_target_kph):
  """Apply the current navigation cap to the stock-cruise button target."""
  if not math.isfinite(planner_target_kph):
    return planner_target_kph
  if math.isfinite(navi_target_kph) and 0 < navi_target_kph <= 250:
    planner_target_kph = min(planner_target_kph, navi_target_kph)
  return max(PORTER_CRUISE_MIN_KPH, planner_target_kph)


def porter_lead_target_kph(target_kph, ego_speed, lead_distance, lead_relative_speed, gap_level, *, lead_visible=True, gap_time_s=None):
  """Lower the conventional-cruise button target before a closing lead reaches the selected gap."""
  values = (target_kph, ego_speed, lead_distance, lead_relative_speed)
  if not lead_visible or not all(math.isfinite(v) for v in values) or ego_speed < 0 or lead_distance <= 0:
    return target_kph
  if lead_relative_speed > 0.2:
    return target_kph

  gap_index = min(len(PORTER_GAP_TIME_S), max(1, int(gap_level or 2))) - 1
  time_s = PORTER_GAP_TIME_S[gap_index]
  if gap_time_s is not None and math.isfinite(gap_time_s) and 0.0 <= gap_time_s <= 30.0:
    time_s = gap_time_s
  desired_distance = max(7.0, 5.0 + ego_speed * time_s)
  projected_distance = lead_distance + min(0.0, lead_relative_speed) * PORTER_LEAD_REACTION_S
  if projected_distance >= desired_distance:
    return target_kph

  lead_speed_kph = max(0.0, ego_speed + lead_relative_speed) * 3.6
  return max(PORTER_CRUISE_MIN_KPH, min(target_kph, lead_speed_kph))


class PorterLeadTracker:
  """Keep brief radar dropouts from releasing a conventional-cruise lead cap."""
  def __init__(self, hold_seconds=PORTER_LEAD_HOLD_S):
    self.hold_seconds = hold_seconds
    self.last_seen = None
    self.last_update = None
    self.distance = 0.0
    self.relative_speed = 0.0
    self.closing = False
    self.opening_since = None
    self.decel_cap = None
    self.decel_cap_time = None

  def update(self, now, target_kph, stock_target_kph, ego_speed, lead_distance,
             lead_relative_speed, gap_level, *, lead_visible=True, gap_time_s=None):
    if (self.last_update is not None and
        (not math.isfinite(now) or now < self.last_update or now - self.last_update > self.hold_seconds)):
      self.decel_cap = self.decel_cap_time = None
    finite_lead = (lead_visible and all(math.isfinite(v) for v in (now, lead_distance, lead_relative_speed)) and
                   lead_distance > 0)
    if finite_lead:
      self.last_seen = now
      self.last_update = now
      self.distance = lead_distance
      self.relative_speed = lead_relative_speed
      if lead_relative_speed > 0.2:
        self.opening_since = now if self.opening_since is None else self.opening_since
      else:
        self.opening_since = None
    elif (self.last_seen is not None and math.isfinite(now) and now >= self.last_seen and
          now - self.last_seen <= self.hold_seconds):
      # Project a closing lead forward while radar briefly loses it. Never
      # project an opening lead farther away during the hold.
      self.distance = max(0.1, self.distance + min(0.0, self.relative_speed) * (now - self.last_update))
      self.last_update = now
      self.opening_since = None
    else:
      self.last_seen = None
      self.last_update = None
      self.closing = False
      self.opening_since = None
      self.decel_cap = self.decel_cap_time = None
      return target_kph

    opening_confirmed = (self.opening_since is not None and
                         now - self.opening_since >= PORTER_LEAD_OPENING_CONFIRM_S)
    self.closing = not opening_confirmed
    # Vision relative speed can briefly cross zero while range is noisy. Keep
    # the existing cap until the lead has pulled away continuously, preventing
    # a transient RES+ request from restoring the memorized cruise speed.
    effective_relative_speed = self.relative_speed if opening_confirmed else min(self.relative_speed, 0.2)
    lead_target_kph = porter_lead_target_kph(
      target_kph, ego_speed, self.distance, effective_relative_speed, gap_level, lead_visible=True, gap_time_s=gap_time_s)
    if opening_confirmed:
      self.decel_cap = self.decel_cap_time = None
    elif lead_target_kph < min(target_kph, stock_target_kph):
      self.decel_cap = lead_target_kph
      self.decel_cap_time = now
    if self.decel_cap_time is not None:
      # One noisy projection must not erase a deceleration target before the
      # next bounded button request. Only a real lead constraint refreshes
      # this timer; ordinary samples cannot prolong an old cap indefinitely.
      if 0 <= now - self.decel_cap_time <= self.hold_seconds:
        lead_target_kph = min(lead_target_kph, self.decel_cap)
      else:
        self.decel_cap = self.decel_cap_time = None
    target_kph = lead_target_kph
    if self.closing and math.isfinite(stock_target_kph):
      # RES can restore the Porter's memorized speed in one large jump. Do not
      # raise the stock setting while a tracked lead is not pulling away.
      target_kph = min(target_kph, stock_target_kph)
    return target_kph


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
          any(str(config.safetyModel) == "hyundai" and config.safetyParam in (1025, 9217, 11265, 25601, 58369, 60417) for config in CP.safetyConfigs))


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
    self.sample_frame = None
    self.sample_seen = 0.0
    self.retry_sample_delay = 0.0
    self.preferred_sample_delay = 0.0
    self.request_sample_delay = 0.0
    self.slot_wait_since = None
    self.last_time = None
    self.next_request = 0.0
    self.direction = 0
    self.baseline = 0
    self.started = 0.0
    self.hold = 0.06
    self.press_count = 0
    self.press_limit = 3
    self.release_count = 0
    self.pending_release = False
    self.acknowledged = False
    self.fault = False
    self.cancel_seen = False
    self.confirm_acceleration = False
    self.accel_since = None
    self.requests = 0
    self.acks = 0
    self.timeouts = 0
    self.consecutive_timeouts = 0
    self.max_consecutive_timeouts = 3
    self.ack_timeout = 0.5
    self.retry_backoff = 3.0

  def _interrupt(self, fresh):
    # A repeated/missing CLU11 sample cannot carry a new release frame. Keep
    # that obligation after aborting the pulse, including a release transition
    # that has not transmitted its first zero yet.
    self.pending_release |= self.phase == "press" or (self.phase == "release" and self.release_count == 0)
    self.phase = "idle"
    if self.pending_release and fresh:
      self.pending_release = False
      return 0
    return None

  def update(self, now, target, current, frame_key, *, enabled, blocked=False,
             manual=False, cancel=False, press_seconds=0.08, gap_seconds=0.3):
    if frame_key != self.sample_frame:
      self.sample_frame = frame_key
      self.sample_seen = now
    fresh = frame_key is not None and frame_key != self.last_frame
    # Each unacknowledged request tries the other RX-relative timing slot.
    # Consume the sample when its delayed slot is reached, so a repeated RX
    # sample can carry one delayed transmission, never a duplicate transmission.
    bypass_delay = (manual or cancel or blocked or not enabled or self.pending_release or
                    frame_key is None or not math.isfinite(now))
    if self.retry_sample_delay and not bypass_delay:
      if fresh and now - self.sample_seen < self.retry_sample_delay - 1e-9:
        self.slot_wait_since = now if self.slot_wait_since is None else self.slot_wait_since
        if now - self.slot_wait_since >= 0.1 - 1e-9:
          # If RX/scheduling never exposes the delayed slot, return to normal
          # timing rather than silently starving all future button requests.
          self.retry_sample_delay = 0.0
          self.slot_wait_since = None
        else:
          fresh = False
      elif fresh:
        self.slot_wait_since = None
    else:
      self.slot_wait_since = None
    if fresh:
      self.last_frame = frame_key
    if not math.isfinite(now) or (self.last_time is not None and now < self.last_time):
      self.fault = True
      self.status = "clock_fault"
      if manual:
        self.phase = "idle"
        self.pending_release = False
        return None
      return self._interrupt(fresh)
    if self.last_time is not None and now - self.last_time > 0.1 + 1e-9:
      # A gap without observations is not continuous target confirmation.
      self.accel_since = None
    self.last_time = now
    if manual:
      self.retry_sample_delay = self.preferred_sample_delay
      self.confirm_acceleration = False
      self.accel_since = None
      self.phase = "idle"
      self.pending_release = False
      self.fault = False
      self.consecutive_timeouts = 0
      self.cancel_seen = False
      self.next_request = now + 0.3
      self.status = "manual"
      return None
    if cancel:
      self.accel_since = None
      self._interrupt(False)
      self.status = "cancel"
      if fresh and not self.cancel_seen:
        self.cancel_seen = True
        self.pending_release = False
        return 4
      return None
    self.cancel_seen = False
    if not enabled:
      self.retry_sample_delay = self.preferred_sample_delay
      self.confirm_acceleration = False
      self.accel_since = None
      self.fault = False
      self.consecutive_timeouts = 0
      self.next_request = now + 0.3
      self.status = "inactive"
      return self._interrupt(fresh)
    finite = all(math.isfinite(v) for v in (target, current, press_seconds, gap_seconds))
    requested_target = target
    if finite:
      target, current = int(target + 0.5), int(current + 0.5)
    valid = (finite and
             PORTER_CRUISE_MIN_KPH <= target <= PORTER_CRUISE_MAX_KPH and
             PORTER_CRUISE_MIN_KPH <= current <= PORTER_CRUISE_MAX_KPH and
             press_seconds > 0 and gap_seconds >= 0)
    if blocked or not valid or frame_key is None:
      self.accel_since = None
      self.next_request = now + 0.3
      self.status = "blocked" if valid else "invalid_input"
      return self._interrupt(fresh)
    if self.confirm_acceleration:
      # After SET-, require a continuously higher target before reversing to
      # RES+. Short planner/lead fluctuations must not undo the reduction.
      # This timer runs during the normal release/ack gap, not after it.
      if requested_target - current >= 1.0 - 1e-5:
        if self.accel_since is None:
          self.accel_since = now
      else:
        self.accel_since = None
    if self.pending_release:
      # Finish the aborted pulse before starting another one, even if the
      # inhibit cleared during a long RX gap. Give the ECU a quiet interval.
      self.next_request = now + max(0.3, gap_seconds)
      self.status = "release"
      return self._interrupt(fresh)
    if self.fault:
      self.status = "fault"
      return None
    if self.phase != "idle":
      change = current - self.baseline
      if change and change * self.direction < 0:
        self.fault = True
        self.status = "wrong_direction"
        return self._interrupt(fresh)
      if change * self.direction > 0:
        if not self.acknowledged:
          self.acks += 1
          self.consecutive_timeouts = 0
          # Remember only a positively acknowledged request in this controller
          # session. Manual/disabled paths cannot learn from physical buttons.
          # Attribute a late ACK to the slot used to start this request, even
          # if scheduling fallback changed the current slot while releasing.
          self.preferred_sample_delay = self.request_sample_delay
        self.acknowledged = True
      if now - self.started >= self.ack_timeout and not self.acknowledged:
        self.timeouts += 1
        self.consecutive_timeouts += 1
        # Do not spend a full failed group repeating a slot already unanswered.
        # Keep the existing quiet periods and three-miss backoff; only the
        # next request's timing changes, never the successful-slot memory.
        self.retry_sample_delay = .01 - self.request_sample_delay
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
        return self._interrupt(fresh)
      if self.phase == "press" and (self.acknowledged or self.press_count >= self.press_limit or
                                    now - self.started >= self.hold - 1e-9):
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
      if (target > current and self.confirm_acceleration and
          (self.accel_since is None or now - self.accel_since < PORTER_BUTTON_ACCEL_CONFIRM_S - 1e-9)):
        self.status = "accel_confirm"
        return None
      if not fresh:
        self.status = "waiting_frame"
        return None
      self.direction = 1 if target > current else -1
      self.confirm_acceleration = self.direction < 0
      self.accel_since = None
      self.baseline = current
      self.started = now
      self.request_sample_delay = self.retry_sample_delay
      # Bound both elapsed time and actual fresh-sample transmissions. At a
      # large uptime, subtraction can put 60 ms just below the threshold and
      # permit a fourth press. Scheduler/RX jitter must not add extra frames.
      self.hold = min(0.06, max(0.04, press_seconds))
      self.press_limit = math.ceil(self.hold / 0.02 - 1e-9)
      self.press_count = 0
      self.next_request = now + max(0.3, gap_seconds)
      self.acknowledged = False
      self.phase = "press"
      self.requests += 1
    self.status = "press"
    if fresh:
      self.press_count += 1
      return 1 if self.direction > 0 else 2
    return None
