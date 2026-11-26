#include <stdbool.h>
#include <stddef.h>

bool safety_tx_buffered_for_fwd = false;

#include "fake_stm.h"
#include "can.h"

//int safety_tx_hook(CANPacket_t *to_send) { return 1; }

#include "faults.h"
#define safety_fwd_hook safety_fwd_hook_packet
#include "safety.h"
#undef safety_fwd_hook

// Python's legacy forwarding tests pass a bus/address rather than a packet.
int safety_fwd_hook(int bus_num, int addr) {
  CANPacket_t packet = {.bus = bus_num, .addr = addr, .data_len_code = 8U};
  return safety_fwd_hook_packet(&packet);
}

#include "drivers/can_common.h"

// libsafety stuff
#include "safety_helpers.h"

// Verify the host declaration against the compiler's firmware packet layout.
int safety_test_packet_size(void) { return sizeof(CANPacket_t); }
int safety_test_packet_data_offset(void) { return offsetof(CANPacket_t, data); }
int safety_test_packet_addr(CANPacket_t *pkt) { return GET_ADDR(pkt); }
int safety_test_packet_bus(CANPacket_t *pkt) { return GET_BUS(pkt); }
int safety_test_packet_len(CANPacket_t *pkt) { return GET_LEN(pkt); }
int safety_test_second_packet_addr(CANPacket_t *pkt) { return GET_ADDR(&pkt[1]); }
