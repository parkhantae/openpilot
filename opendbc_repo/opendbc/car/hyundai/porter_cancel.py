"""Porter low-target cancellation and bounded CANCEL-button transmission."""
import math

from opendbc.car.hyundai.porter import PORTER_CRUISE_MAX_KPH, PORTER_LEAD_REACTION_S, porter_lead_target_kph


def porter_cancel_target(planner, selected, navigation, ego, distance, relative, gap, *,
                         lead_visible=False, gap_time_s=None, reaction_s=PORTER_LEAD_REACTION_S):
  # Zero navigation/selected values mean unavailable; zero planner speed is a stop.
  candidates = [v for v in (selected, navigation) if v is not None and math.isfinite(v) and 0 < v <= 250]
  if planner is not None and math.isfinite(planner) and 0 <= planner <= 250:
    candidates.append(planner)
  if lead_visible and all(math.isfinite(v) for v in (ego, distance, relative)) and ego >= 0 and distance > 0:
    lead_speed = max(0., ego + relative) * 3.6
    # Reuse the existing selected-lead constraint without changing its 30 floor.
    cap = porter_lead_target_kph(PORTER_CRUISE_MAX_KPH, ego, distance, relative, gap,
                               gap_time_s=gap_time_s, reaction_s=reaction_s)
    if cap <= 30 and lead_speed < 30:
      candidates.append(lead_speed)
  return min(candidates) if candidates else None


class PorterLowSpeedCancel:
  def __init__(self):
    self.since = None
    self.last_time = None
    self.active = False

  def update(self, now, target, *, eligible, cruise_enabled):
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now if math.isfinite(now) else None
    if not eligible or not cruise_enabled:
      self.since, self.active = None, False
      return False
    if self.active:
      return True  # Finish cancellation until stock OFF; never engage/resume.
    if not clock_ok:
      self.since = None
      return False
    below = target is not None and math.isfinite(target) and 0 <= target < 30 - 1e-5
    if not below:
      self.since = None
      return False
    if self.since is None:
      self.since = now
    self.active = now - self.since >= .3 - 1e-9
    return self.active


class PorterCancelButtons:
  """Bounded CANCEL/release until OEM OFF, with feedback waits and driver priority."""
  def __init__(self):
    self.phase = 'idle'
    self.busy = False
    self.status = 'idle'
    self.rx_key = self.sent_key = None
    self.sample_seen = 0.
    self.last_time = None
    self.started = 0.
    self.next_request = 0.
    self.frames = 0
    self.requests = 0
    self.group_attempts = 0
    self.event_attempts = 0
    self.delay = 0.
    self.slot_wait_since = None

  def update(self, now, key, *, requested, stock_enabled, valid=True, manual=False, preferred_delay=0.):
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now if math.isfinite(now) else None
    if key is not None and key != self.rx_key:
      self.rx_key, self.sample_seen = key, now
    fresh = valid and key is not None and key != self.sent_key

    def send(button):
      self.sent_key = key
      return button

    if not clock_ok:
      self.next_request = now + .5 if math.isfinite(now) else 0.
    if manual or not requested or not stock_enabled or not valid or not clock_ok:
      if self.phase == 'press':
        self.phase = 'release'
      elif self.phase != 'release':
        self.phase = 'idle'
      self.slot_wait_since = None
      if not requested or not stock_enabled:
        self.group_attempts = self.event_attempts = 0
        self.next_request = 0.
      self.busy = self.phase == 'release'
      self.status = 'manual' if manual else ('off_confirmed' if not stock_enabled else 'interrupted')
      if self.phase == 'release' and fresh and not manual:
        self.phase = 'idle'
        self.busy = False
        return send(0)
      return None

    self.busy = True
    if self.phase == 'press' and (now - self.started >= .06 - 1e-9 or self.frames >= 3):
      self.phase = 'release'
    if self.phase == 'release':
      self.status = 'release'
      if fresh:
        self.phase = 'wait'
        self.next_request = now + (3. if self.group_attempts >= 3 else .5)
        if self.group_attempts >= 3:
          self.group_attempts = 0
        return send(0)
      return None
    if self.phase != 'press':
      self.delay = preferred_delay if self.event_attempts % 2 == 0 else .01 - preferred_delay
      self.delay = .01 if self.delay >= .005 else 0.
      if now < self.next_request:
        self.status = 'waiting_off'
        return None
      if not fresh or now - self.sample_seen < self.delay - 1e-9:
        self.slot_wait_since = now if self.slot_wait_since is None else self.slot_wait_since
        if fresh and now - self.slot_wait_since >= .1 - 1e-9:
          # A scheduling pattern without a delayed slot must not starve CANCEL.
          self.delay = 0.
        else:
          self.status = 'waiting_frame'
          return None
      self.slot_wait_since = None
      self.phase = 'press'
      self.started = now
      self.frames = 0
      self.requests += 1
      self.event_attempts += 1
      self.group_attempts += 1
    self.status = 'press'
    if fresh and now - self.sample_seen >= self.delay - 1e-9:
      self.frames += 1
      return send(4)
    return None
