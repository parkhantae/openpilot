"""One-shot local speed initialization after a qualified Porter SET response."""

import math

from opendbc.car.hyundai.porter import porter_conventional_cruise


class PorterSetSpeedSync:
  def __init__(self):
    self.last_time = None
    self.previous_gas = False
    self.previous_stock = False
    self.press_since = None
    self.pending_since = None
    self.requested = False

  def update(self, now, CP, CS, CC, *, configured, speed_from_pcm, manual=False):
    stock = CS.cruiseState.enabled
    rising = stock and not self.previous_stock
    press = not self.previous_gas and CS.gasPressed
    release = self.previous_gas and not CS.gasPressed
    self.previous_stock, self.previous_gas = stock, CS.gasPressed
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= 0.1 + 1e-9)
    self.last_time = now if math.isfinite(now) else None
    valid = (
      clock_ok
      and configured
      and porter_conventional_cruise(CP)
      and speed_from_pcm == 0
      and any(c.safetyParam == 15489 for c in CP.safetyConfigs)
      and CS.canValid
      and not CS.canTimeout
      and not CS.accFaulted
      and CS.gearShifter == 'drive'
      and CS.cruiseState.available
      and not (CS.brakePressed or CS.brakeHoldActive or CS.parkingBrake or CC.cruiseControl.cancel or manual)
    )
    if not valid:
      self.press_since = self.pending_since = None
      return None
    if CS.gasPressed:
      self.pending_since = None
      if not stock and press:
        self.press_since = now
      elif stock:
        self.press_since = None
      return None
    if release:
      cluster = round(CS.vEgoCluster * 3.6, 3)
      if self.press_since is not None and now - self.press_since >= 0.1 - 1e-9 and (not stock or rising) and math.isfinite(cluster) and 30 <= cluster <= 160:
        self.pending_since = now
        self.requested = False
      self.press_since = None
    if self.pending_since is not None:
      age = now - self.pending_since
      if age <= 0.1 + 1e-9 and CC.cruiseControl.resume:
        self.requested = True
      if age < 0 or age > 0.5 + 1e-9 or (not self.requested and age > 0.1 + 1e-9) or (self.requested and not stock and not CC.cruiseControl.resume):
        self.pending_since = None
      elif rising and self.requested:
        # Use the first confirmed OEM setting, never the pedal's peak speed or
        # a continuously mirrored setting that would undo local gap control.
        self.pending_since = None
        speed = round(CS.cruiseState.speed * 3.6, 3)
        if math.isfinite(speed) and 30 <= speed <= 160:
          return speed
    return None
