"""One fresh, driver-authorized SET to replace an already-active OEM setting."""
import math


def pedal_set_profile_ready(cp):
  # The two profiles produced by the current Porter interface. Active cruise
  # needs no standby authorization, so AutoSetMain OFF (1025) also works.
  return any(c.safetyParam in (1025, 15489) for c in cp.safetyConfigs)


def pedal_capture_safe(speed, target, ego, distance, relative, *, visible, held, gap_time, reaction, spacing, cluster_ratio=1.):
  if not all(math.isfinite(v) for v in (speed, target, ego, gap_time, reaction, spacing, cluster_ratio)):
    return False
  if not (30 <= speed <= 160 and speed <= target + 1e-5 and ego >= 0 and
          .3 <= gap_time <= 30 and 4 <= reaction <= 8 and spacing >= .3 and .5 <= cluster_ratio <= 1.5):
    return False
  if not visible:
    return not held
  if not all(math.isfinite(v) for v in (distance, relative)) or distance <= 0:
    return False
  lead_speed = max(0., ego + relative) * 3.6 / cluster_ratio
  steps = math.ceil(max(0., speed - max(30., lead_speed)) - 1e-9)
  approach = reaction + steps * spacing
  margin = distance - max(7., 5. + ego * gap_time)
  return (margin + min(0., relative) * approach >= 0 and
          speed <= max(30., lead_speed + margin / approach * 3.6 / cluster_ratio) + 1e-5)


class PorterPedalCapture:
  def __init__(self):
    self.last_time = None
    self.previous_gas = None
    self.gas_since = None
    self.speed = 0.
    self.stamp = 0
    self.until = 0.

  def clear(self):
    self.speed, self.stamp, self.until = 0., 0, 0.

  def observe(self, now, gas, eligible):
    continuous = self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9
    self.last_time = now
    cue = False
    if not math.isfinite(now) or not continuous or not eligible:
      self.gas_since = None
      self.clear()
    elif gas:
      self.clear()
      if self.previous_gas is False:
        self.gas_since = now
    elif self.previous_gas:
      cue = self.gas_since is not None and now - self.gas_since >= .1 - 1e-9
      self.gas_since = None
    self.previous_gas = gas
    return cue


class PorterPedalSet:
  def __init__(self):
    self.seen_stamp = 0
    self.stamp = 0
    self.last_key = None
    self.last_tx_ns = None
    self.started_ns = 0
    self.quiet_until_ns = 0
    self.baseline = self.speed = 0.
    self.frames = 0
    self.phase = 'idle'
    self.pending_release = False
    self.requests = self.acks = self.timeouts = 0
    self.status = 'idle'
    self.last_now_ns = None

  @property
  def busy(self):
    return self.phase != 'idle' or self.pending_release

  def update(self, now_ns, stamp, speed, current, key, *, enabled, blocked, manual, gas, sample_age_s):
    fresh = key is not None and key != self.last_key
    if fresh:
      self.last_key = key
    new_cue = stamp > 0 and stamp != self.seen_stamp
    if new_cue:
      self.seen_stamp = stamp  # Blocked/expired cues are consumed, never queued.
    clock_ok = self.last_now_ns is None or 0 <= now_ns - self.last_now_ns <= 100_000_000
    self.last_now_ns = now_ns
    valid = (clock_ok and enabled and not blocked and not manual and not gas and
             all(math.isfinite(v) for v in (speed, current, sample_age_s)) and
             30 - 1e-5 <= current <= 160 + 1e-5)

    def abort(reason):
      self.pending_release |= self.phase == 'press'
      self.phase = 'idle'
      self.status = reason

    if not valid:
      abort('interrupted')
    elif self.phase != 'idle':
      if current >= self.speed - .5:
        self.acks += int(self.phase != 'armed')
        abort('acknowledged')
      elif current < self.baseline - .5:
        abort('wrong_direction')
      elif self.phase == 'armed' and now_ns - self.stamp > 100_000_000:
        abort('expired')
      elif self.phase != 'armed' and now_ns - self.started_ns > 500_000_000:
        self.timeouts += 1
        abort('no_response')
      elif stamp != self.stamp or speed != self.speed:
        abort('withdrawn')
    if self.pending_release:
      if fresh and not manual:
        self.pending_release = False
        self.last_tx_ns = now_ns
        self.quiet_until_ns = max(self.quiet_until_ns, now_ns + 3_000_000_000)
        return 0
      return None
    if not valid:
      return None
    if self.phase == 'idle' and new_cue:
      if not (30 <= speed <= 160 and speed >= current + 1 - 1e-5 and
              0 <= now_ns - stamp <= 100_000_000 and stamp >= self.quiet_until_ns):
        self.status = 'ineligible'
        return None
      self.stamp, self.speed, self.baseline = stamp, speed, current
      self.phase = 'armed'
    if self.phase == 'armed':
      if not fresh or not 0 <= sample_age_s <= .008 + 1e-9:
        return None
      self.started_ns, self.frames, self.phase = now_ns, 0, 'press'
      self.requests += 1
      self.quiet_until_ns = now_ns + 3_000_000_000
    if self.phase == 'press':
      if now_ns - self.started_ns >= 60_000_000 or self.frames >= 3:
        self.phase = 'wait'
        if fresh:
          self.last_tx_ns = now_ns
          self.quiet_until_ns = max(self.quiet_until_ns, now_ns + 3_000_000_000)
          return 0
        self.pending_release = True
      elif (fresh and 0 <= sample_age_s <= .008 + 1e-9 and
            (self.last_tx_ns is None or now_ns - self.last_tx_ns >= 15_000_000)):
        self.frames += 1
        self.last_tx_ns = now_ns
        self.status = 'press'
        return 2
    return None
