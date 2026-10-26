"""Offline button-decision prototype. No CAN output or openpilot integration.

All timing/range values must come from bench measurements, not this module.
Inputs must be decoded, fresh OEM states; never substitute wheel speed for
the OEM cruise set speed. Returned labels are abstract test events, not CAN.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class State:
    enabled: bool
    cruise_enabled: bool
    drive: bool
    brake: bool
    gas: bool
    manual_button: bool
    fault: bool
    standstill: bool
    valid: bool
    received_at: float
    set_speed: float  # km/h, decoded OEM cruise setting


class ButtonDecider:
    def __init__(self, *, minimum, maximum, interval, ack_timeout, max_age):
        values = (minimum, maximum, interval, ack_timeout, max_age)
        if not all(isfinite(v) for v in values):
            raise ValueError("Configuration must be finite")
        if not (0 < minimum < maximum and 0 < interval <= ack_timeout and max_age > 0):
            raise ValueError("Invalid range or timing")
        self.minimum, self.maximum = minimum, maximum
        self.interval, self.ack_timeout, self.max_age = interval, ack_timeout, max_age
        self.last_time = None
        self.next_allowed = float("-inf")
        self.pending = None
        self.blocked = False

    def update(self, now: float, target: float, state: State):
        """Return RES_ACCEL, SET_DECEL, or None; never engage/resume cruise.

        One request is allowed at a time. A later fresh OEM setting must
        change in the requested direction before another request is allowed.
        An unacknowledged request latches output off until explicit disable.
        A transport adapter, pulse/release protocol and safety validation are
        deliberately absent. Do not call this directly from a CAN sender.
        """
        if not isfinite(now) or (self.last_time is not None and now < self.last_time):
            self.blocked = True
            self.pending = None
            return None
        self.last_time = now
        if not state.enabled:
            self.pending = None
            self.blocked = False
            self.next_allowed = now + self.interval
            return None
        valid = (state.valid and isfinite(state.received_at)
                 and 0 <= now - state.received_at <= self.max_age
                 and isfinite(state.set_speed) and isfinite(target)
                 and self.minimum <= state.set_speed <= self.maximum
                 and self.minimum <= target <= self.maximum)
        interlock = (not state.cruise_enabled or not state.drive or state.brake
                     or state.gas or state.manual_button or state.fault or state.standstill)
        if not valid or interlock:
            # A lost state or driver intervention invalidates any in-flight
            # request; require explicit disable before rearming.
            self.pending = None
            self.blocked = True
            return None
        if self.blocked:
            return None
        if self.pending is not None:
            sent_at, old_speed, direction = self.pending
            if now - sent_at >= self.ack_timeout:
                self.pending = None
                self.blocked = True
                return None
            if state.received_at <= sent_at or state.set_speed == old_speed:
                return None
            if (state.set_speed - old_speed) * direction <= 0:
                self.pending = None
                self.blocked = True
                return None
            self.pending = None
        if now < self.next_allowed or abs(target - state.set_speed) < 0.5:
            return None
        direction = 1 if target > state.set_speed else -1
        self.pending = (now, state.set_speed, direction)
        self.next_allowed = now + self.interval
        return "RES_ACCEL" if direction > 0 else "SET_DECEL"
