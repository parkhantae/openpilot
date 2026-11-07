#pragma once

// Legacy driver-pedal-authorized double SET. Six SET frames total, never more than
// three/60ms per press, an explicit >=60ms release gap, and a 240ms envelope.
// Profile15489 instead allows one <=120ms/six-frame press, ending on release.
// Both profiles require another pedal cycle and three seconds after the last TX.
typedef struct {
  bool pedal;
  bool grant;
  bool seen;
  bool active;
  bool second;
  bool released;
  uint32_t pedal_ts;
  uint32_t grant_ts;
  uint32_t start_ts;
  uint32_t press_ts;
  uint32_t release_ts;
  uint32_t last_tx_ts;
  int frames;
  int press_frames;
} HyundaiPorterPair;

static HyundaiPorterPair hyundai_porter_pair;

static void hyundai_porter_pair_cancel(void) {
  hyundai_porter_pair.pedal = false;
  hyundai_porter_pair.grant = false;
  hyundai_porter_pair.active = false;
}

static void hyundai_porter_pair_pedal(uint32_t now, bool gas, bool eligible, bool speed_ok) {
  if (!eligible) {
    hyundai_porter_pair_cancel();
  } else if (gas) {
    hyundai_porter_pair.active = false;
    hyundai_porter_pair.grant = false;
    if (!hyundai_porter_pair.pedal) {
      hyundai_porter_pair.pedal = true;
      hyundai_porter_pair.pedal_ts = now;
    }
  } else {
    if (hyundai_porter_pair.pedal && speed_ok && get_ts_elapsed(now, hyundai_porter_pair.pedal_ts) >= 100000U) {
      hyundai_porter_pair.grant = true;
      hyundai_porter_pair.grant_ts = now;
    }
    hyundai_porter_pair.pedal = false;
    if (hyundai_porter_pair.grant && get_ts_elapsed(now, hyundai_porter_pair.grant_ts) > 100000U) {
      hyundai_porter_pair.grant = false;
    }
  }
}

static bool hyundai_porter_pair_normal_steps(uint32_t now) {
  // During this window only the bounded pair path may continue SET after ON;
  // normal speed-control frames must not add a third press to the pair.
  return !hyundai_porter_pair.seen || get_ts_elapsed(now, hyundai_porter_pair.start_ts) >= 240000U;
}

static bool hyundai_porter_pair_tx(uint32_t now, int button, bool fresh, bool allowed, bool settled, bool standby, bool single_long) {
  if (button == HYUNDAI_BTN_NONE) {
    if (fresh && hyundai_porter_pair.active) {
      if (!hyundai_porter_pair.released) {
        hyundai_porter_pair.released = true;
        hyundai_porter_pair.release_ts = now;
        hyundai_porter_pair.last_tx_ts = now;
        if (single_long || hyundai_porter_pair.second) hyundai_porter_pair.active = false;
      }
    }
    return true;
  }
  if (button != HYUNDAI_BTN_SET || !allowed) {
    hyundai_porter_pair_cancel();
    return false;
  }
  if (!fresh || !settled) return false;
  if (!hyundai_porter_pair.active) {
    bool cue = hyundai_porter_pair.grant && get_ts_elapsed(now, hyundai_porter_pair.grant_ts) <= 100000U;
    bool quiet = !hyundai_porter_pair.seen || get_ts_elapsed(now, hyundai_porter_pair.last_tx_ts) >= 3000000U;
    if (!standby || !cue || !quiet) return false;
    hyundai_porter_pair.grant = false;
    hyundai_porter_pair.seen = true;
    hyundai_porter_pair.active = true;
    hyundai_porter_pair.second = false;
    hyundai_porter_pair.released = false;
    hyundai_porter_pair.start_ts = hyundai_porter_pair.press_ts = now;
    hyundai_porter_pair.frames = hyundai_porter_pair.press_frames = 0;
  }
  if (hyundai_porter_pair.released) {
    if (hyundai_porter_pair.second || get_ts_elapsed(now, hyundai_porter_pair.release_ts) < 60000U) return false;
    hyundai_porter_pair.second = true;
    hyundai_porter_pair.released = false;
    hyundai_porter_pair.press_ts = now;
    hyundai_porter_pair.press_frames = 0;
  }
  if (get_ts_elapsed(now, hyundai_porter_pair.start_ts) >= (single_long ? 120000U : 240000U) ||
      get_ts_elapsed(now, hyundai_porter_pair.press_ts) >= (single_long ? 120000U : 60000U) ||
      hyundai_porter_pair.frames >= 6 || hyundai_porter_pair.press_frames >= (single_long ? 6 : 3)) {
    hyundai_porter_pair.active = false;
    return false;
  }
  hyundai_porter_pair.frames += 1;
  hyundai_porter_pair.press_frames += 1;
  hyundai_porter_pair.last_tx_ts = now;
  return true;
}
