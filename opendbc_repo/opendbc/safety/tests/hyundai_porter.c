// Native harness for the production safety implementation, without a vehicle.
#include <stdbool.h>
bool safety_tx_buffered_for_fwd = false;
#include "libsafety/safety.c"
