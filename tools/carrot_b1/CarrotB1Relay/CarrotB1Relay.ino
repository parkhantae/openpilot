// Porter contact-output variant. No TWAI driver, CAN decoder or CAN transmission.
#include <Arduino.h>
#include <driver/gpio.h>
#include <esp_app_desc.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <BLEDevice.h>
#include <BLESecurity.h>
#include <Preferences.h>
#include <mbedtls/sha256.h>
#include <mbedtls/md.h>
#include "B1Relay.h"
#include "B1Ota.h"

// PROVISIONAL bench pin map: confirm board and active-HIGH driver before wiring.
// External pull-downs and normally-open contacts are required for reset/power loss.
constexpr uint8_t LEFT_GPIO = 4, RIGHT_GPIO = 5;
static_assert(LEFT_GPIO != RIGHT_GPIO);
constexpr char SERVICE[] = "db340a90-804c-4ead-af37-8a0e6af754a1";
constexpr char META[] = "db340a92-804c-4ead-af37-8a0e6af754a1";
constexpr char CONTROL[] = "db340a93-804c-4ead-af37-8a0e6af754a1";
constexpr char RELEASE_TAG[] = "carrot-b1-relay-release=1";
struct __attribute__((packed)) Request {
  uint32_t session, stamp;
  uint16_t seq;
  uint8_t op, ttl5ms, tag[8];
};
// v3 byte 11 describes requested relay outputs, never physical vehicle lamps.
struct __attribute__((packed)) Report {
  uint32_t session, stamp;
  uint16_t ack;
  uint8_t state, outputs, version;
  uint16_t lastSeq;
};
struct Claim { uint32_t session; uint8_t seed[16]; };
static_assert(sizeof(Request) == 20 && sizeof(Report) == 15 && sizeof(Claim) == 20);
Preferences prefs;
uint8_t key[32];
QueueHandle_t inbox, claims;
bool claimed = false;
BLECharacteristic *metaValue, *statusValue, *traceValue;
char buildId[65];
b1relay::Controller relay;
portMUX_TYPE outputMux = portMUX_INITIALIZER_UNLOCKED;
esp_timer_handle_t safetyTimer;
uint8_t applied = 0;

// Only call with outputMux held. De-energize both before changing direction.
void applyLocked() {
  uint8_t mask = relay.mask;
  if (mask != 1 && mask != 2) mask = 0;
  if (mask == applied) return;
  gpio_set_level(gpio_num_t(LEFT_GPIO), LOW); gpio_set_level(gpio_num_t(RIGHT_GPIO), LOW);
  if (mask == 1) gpio_set_level(gpio_num_t(LEFT_GPIO), HIGH);
  else if (mask == 2) gpio_set_level(gpio_num_t(RIGHT_GPIO), HIGH);
  applied = mask;
}
void shutdownOutputs() {
  portENTER_CRITICAL(&outputMux);
  relay.connect(0, millis()); applyLocked();
  portEXIT_CRITICAL(&outputMux);
}
void safetyTick(void*) {
  portENTER_CRITICAL(&outputMux);
  relay.tick(millis()); applyLocked();
  portEXIT_CRITICAL(&outputMux);
}
class Link : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    portENTER_CRITICAL(&outputMux);
    relay.connect(esp_random() | 1U, millis()); applyLocked();
    portEXIT_CRITICAL(&outputMux);
  }
  void onConnect(BLEServer *s, ble_gap_conn_desc *event) override {
    s->updateConnParams(event->conn_handle, 8, 12, 0, 400);
  }
  void onDisconnect(BLEServer *s) override { shutdownOutputs(); s->startAdvertising(); }
};
class Writer : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String value = c->getValue();
    if (value.length() != sizeof(Request)) return;
    Request r; memcpy(&r, value.c_str(), sizeof(r));
    // Key use/rotation and authentication stay on the main loop, outside callbacks.
    xQueueSend(inbox, &r, 0);
  }
};
class ClaimWriter : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String value = c->getValue();
    if (value.length() != sizeof(Claim)) return;
    Claim claim; memcpy(&claim, value.c_str(), sizeof(claim));
    xQueueSend(claims, &claim, 0);
  }
};
void setup() {
  // Latch OFF before enabling output; no NVS/BLE/flash work precedes this.
  gpio_set_level(gpio_num_t(LEFT_GPIO), LOW); gpio_set_level(gpio_num_t(RIGHT_GPIO), LOW);
  pinMode(LEFT_GPIO, OUTPUT); pinMode(RIGHT_GPIO, OUTPUT);
  if (esp_register_shutdown_handler(shutdownOutputs) != ESP_OK) {
    shutdownOutputs(); while (true) delay(1000);
  }
  esp_timer_create_args_t args = {};
  args.callback = safetyTick; args.name = "b1-relay-cutoff";
  if (esp_timer_create(&args, &safetyTimer) != ESP_OK ||
      esp_timer_start_periodic(safetyTimer, 1000) != ESP_OK) {
    shutdownOutputs(); while (true) delay(1000);
  }
  Serial.begin(115200);
  const auto *app = esp_app_get_description();
  for (size_t i = 0; i < sizeof(app->app_elf_sha256); ++i)
    snprintf(buildId + 2*i, 3, "%02x", app->app_elf_sha256[i]);
  inbox = xQueueCreate(8, sizeof(Request)); claims = xQueueCreate(1, sizeof(Claim));
  if (!inbox || !claims || !prefs.begin("carrot-b1", false)) {
    shutdownOutputs(); while (true) delay(1000);
  }
  if (prefs.getBytesLength("auth") != sizeof(key)) {
    esp_fill_random(key, sizeof(key));
    if (prefs.putBytes("auth", key, sizeof(key)) != sizeof(key)) {
      shutdownOutputs(); while (true) delay(1000);
    }
  }
  if (prefs.getBytes("auth", key, sizeof(key)) != sizeof(key)) {
    shutdownOutputs(); while (true) delay(1000);
  }
  claimed = prefs.getBytesLength("owner-key") == sizeof(key);
  if (claimed && prefs.getBytes("owner-key", key, sizeof(key)) != sizeof(key)) {
    shutdownOutputs(); while (true) delay(1000);
  }
  BLEDevice::init("Carrot-B1"); BLEDevice::setMTU(517);
  BLESecurity::setCapability(ESP_IO_CAP_NONE);
  BLESecurity::setAuthenticationMode(true, false, true);
  auto *server = BLEDevice::createServer(); server->setCallbacks(new Link());
  auto *svc = server->createService(SERVICE);
  statusValue = svc->createCharacteristic("db340a91-804c-4ead-af37-8a0e6af754a1", BLECharacteristic::PROPERTY_READ);
  metaValue = svc->createCharacteristic(META, BLECharacteristic::PROPERTY_READ);
  traceValue = svc->createCharacteristic("db340a96-804c-4ead-af37-8a0e6af754a1", BLECharacteristic::PROPERTY_READ);
  svc->createCharacteristic(CONTROL, BLECharacteristic::PROPERTY_WRITE)->setCallbacks(new Writer());
  auto *claim = svc->createCharacteristic("db340a95-804c-4ead-af37-8a0e6af754a1", BLECharacteristic::PROPERTY_WRITE);
  claim->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
  claim->setCallbacks(new ClaimWriter());
  ota::setup(svc);
  svc->start(); BLEDevice::getAdvertising()->addServiceUUID(SERVICE);
  BLEDevice::getAdvertising()->setScanResponse(true); BLEDevice::startAdvertising();
}
void loop() {
  uint32_t sid; bool active;
  portENTER_CRITICAL(&outputMux);
  sid = relay.session; active = relay.mask != 0;
  portEXIT_CRITICAL(&outputMux);
  // No CAN exists in this build; a quiet interval is measured from boot.
  ota::tick(millis(), sid, active, key);
  Claim candidate;
  if (xQueueReceive(claims, &candidate, 0) == pdTRUE && !claimed && sid &&
      candidate.session == sid && millis() < 180000 && !active && !ota::busy && !ota::reboot) {
    uint8_t nextKey[32];
    if (!mbedtls_sha256(candidate.seed, sizeof(candidate.seed), nextKey, 0) &&
        prefs.putBytes("owner-key", nextKey, sizeof(nextKey)) == sizeof(nextKey)) {
      memcpy(key, nextKey, sizeof(key)); claimed = true;
      xQueueReset(inbox);
    }
  }
  Request r;
  // Bounded drain: command flood must not starve status, OTA or session checks.
  for (unsigned i = 0; i < 8 && xQueueReceive(inbox, &r, 0) == pdTRUE; ++i) {
    if (ota::busy || ota::reboot) continue;
    uint8_t digest[32], diff = 0;
    if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, sizeof(key),
                        (uint8_t*)&r, offsetof(Request, tag), digest)) continue;
    for (unsigned j = 0; j < sizeof(r.tag); ++j) diff |= r.tag[j] ^ digest[j];
    if (diff) continue;
    // Unclaimed boards accept authenticated STOP for recovery/proof, never output.
    if (!claimed && r.op != b1relay::Stop) continue;
    b1relay::Request req = {r.session, r.stamp, r.seq, r.op, r.ttl5ms};
    portENTER_CRITICAL(&outputMux);
    relay.accept(req, millis()); applyLocked();
    portEXIT_CRITICAL(&outputMux);
  }
  uint32_t now = millis();
  static uint32_t published = 0;
  if (now - published >= 20) {
    published = now;
    portENTER_CRITICAL(&outputMux);
    relay.tick(now); applyLocked();
    Report report = {relay.session, now, relay.ack,
      uint8_t(relay.fault ? 5 : (relay.mask || now - relay.offAt < b1relay::OFF_MS) ? 3 : 1), relay.mask, b1relay::VERSION, relay.lastSeq};
    const char *reason = relay.reason;
    portEXIT_CRITICAL(&outputMux);
    metaValue->setValue((uint8_t*)&report, sizeof(report));
    char trace[192];
    snprintf(trace, sizeof(trace), "mode=relay outputs=%u reason=%s elf=%s %s",
             report.outputs, reason, buildId, RELEASE_TAG);
    traceValue->setValue(trace);
    statusValue->setValue("relay: no lamp feedback");
  }
  static char cmd[12]; static unsigned pos = 0;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      cmd[pos] = 0; pos = 0;
      if (!strcmp(cmd, "PAIR")) {
        Serial.print("PAIR "); for (uint8_t b : key) Serial.printf("%02x", b); Serial.println();
      }
    } else if (ch != '\r' && pos < sizeof(cmd)-1) cmd[pos++] = ch;
  }
  delay(1);
}
