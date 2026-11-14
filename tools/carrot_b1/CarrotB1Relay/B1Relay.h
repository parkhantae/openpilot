#pragma once
#include <stdint.h>

namespace b1relay {
// All times use uint32_t elapsed arithmetic, including millis() rollover.
constexpr uint32_t PULSE_MS = 250;
constexpr uint32_t MAX_ON_MS = 10000;
constexpr uint32_t OFF_MS = 100;
constexpr uint8_t VERSION = 3;
enum Op : uint8_t { Lease, Left, Right, Stop, HoldLeft, HoldRight };
struct Request { uint32_t session, stamp; uint16_t seq; uint8_t op, ttl5ms; };

// Caller serializes access, applies mask to hardware under the same lock,
// and calls tick independently of BLE/OTA/main-loop progress.
class Controller {
public:
  uint32_t session = 0, deadline = 0, started = 0, offAt = 0;
  uint16_t lastSeq = 0, ack = 0;
  uint8_t mask = 0;
  bool leased = false, held = false, fault = false;
  const char *reason = "boot_off";

  void off(uint32_t now, const char *why, bool keepAck = false) {
    if (mask) offAt = now;
    mask = 0; held = false;
    if (!keepAck) ack = 0;
    reason = why;
  }
  void connect(uint32_t sid, uint32_t now) {
    off(now, "session_changed");
    session = sid; lastSeq = 0; leased = false;
    // A disconnect/reconnect cannot clear a max-time/overlap fault.
  }
  void tick(uint32_t now) {
    if (mask && now - started >= MAX_ON_MS) {
      fault = true; leased = false; off(now, "max_on_time");
    } else if (leased && int32_t(deadline - now) <= 0) {
      leased = false; off(now, "lease_expired");
    } else if (mask && !held && now - started >= PULSE_MS) {
      off(now, "pulse_complete", true);
    }
  }
  bool accept(const Request &r, uint32_t now) {
    tick(now);
    if (!session || r.session != session || int16_t(r.seq - lastSeq) <= 0 ||
        !r.ttl5ms || r.ttl5ms > 70 || r.op > HoldRight ||
        now - r.stamp >= uint32_t(r.ttl5ms) * 5) return false;
    lastSeq = r.seq;
    if (r.op == Stop) {
      leased = false; fault = false; off(now, "stop"); return true;
    }
    if (fault) return true; // sequence proof works, output remains latched OFF
    deadline = r.stamp + uint32_t(r.ttl5ms) * 5;
    leased = true;
    if (r.op == Lease) {
      // Ending a held request releases immediately; a tap retains its fixed pulse.
      if (held) off(now, "hold_released");
      return true;
    }
    if (r.op == HoldLeft || r.op == HoldRight) {
      uint8_t wanted = r.op == HoldLeft ? 1 : 2;
      if (mask == wanted && ack) held = true;
      else if (mask) {
        fault = true; leased = false; off(now, "opposite_hold");
      }
      // Holds never start/restart output, including after a timeout.
      return true;
    }
    if (mask) {
      fault = true; leased = false; off(now, "overlapping_start"); return true;
    }
    if (now - offAt < OFF_MS) { reason = "off_interval"; return true; }
    mask = r.op == Left ? 1 : 2;
    started = now; held = false; ack = r.seq; reason = "contact_requested";
    return true;
  }
};
}
