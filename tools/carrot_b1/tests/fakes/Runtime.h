#pragma once
// Desktop-only doubles for the real .ino integration tests. No device I/O.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
#include <deque>
#include <map>
#include <mutex>
#include <openssl/hmac.h>
#include <openssl/sha.h>
using String = std::string;
inline uint32_t fakeMillis=0;
inline uint32_t millis() { return fakeMillis; }
inline void delay(unsigned) {}
constexpr int LOW=0, HIGH=1, OUTPUT=1, ESP_OK=0, pdTRUE=1, ESP_IO_CAP_NONE=0, ESP_GATT_PERM_WRITE_ENCRYPTED=1;
inline int pins[64]={};
inline bool pinConflict=false;
inline void digitalWrite(int pin,int level) { pins[pin]=level; if(pins[4] && pins[5]) pinConflict=true; }
using gpio_num_t=int;
inline int gpio_set_level(gpio_num_t pin,int level) { digitalWrite(pin,level);return ESP_OK; }
inline void pinMode(int,int) {}
using portMUX_TYPE=std::mutex;
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(m) (m)->lock()
#define portEXIT_CRITICAL(m) (m)->unlock()
struct Queue { size_t capacity,size; std::deque<std::vector<uint8_t>> items; };
using QueueHandle_t=Queue*;
inline QueueHandle_t xQueueCreate(size_t count,size_t size) { return new Queue{count,size,{}}; }
inline int xQueueSend(QueueHandle_t q,const void *data,int) {
 if (q->items.size()==q->capacity) return 0;
 const auto *b=static_cast<const uint8_t*>(data);q->items.emplace_back(b,b+q->size);return pdTRUE;
}
inline int xQueueReceive(QueueHandle_t q,void *data,int) {
 if (q->items.empty()) return 0;
 memcpy(data,q->items.front().data(),q->size);q->items.pop_front();return pdTRUE;
}
inline void xQueueReset(QueueHandle_t q) { q->items.clear(); }
struct SerialType {
 void begin(int) {} int available() { return 0; } char read() { return 0; }
 void print(const char*) {} void println() {}
 template<class... T> void printf(const char*, T...) {}
};
inline SerialType Serial;
inline std::map<std::string,std::vector<uint8_t>> nvs;
struct Preferences {
 bool begin(const char*,bool) { return true; }
 size_t getBytesLength(const char *s) { return nvs[s].size(); }
 size_t putBytes(const char *s,const void *p,size_t n) {
  auto *b=static_cast<const uint8_t*>(p);nvs[s]=std::vector<uint8_t>(b,b+n);return n;
 }
 size_t getBytes(const char *s,void *p,size_t n) {
  size_t k=std::min(n,nvs[s].size());memcpy(p,nvs[s].data(),k);return k;
 }
};
inline uint32_t esp_random() { static uint32_t n=100;return ++n; }
inline void esp_fill_random(void *p,size_t n) { memset(p,17,n); }
struct App { uint8_t app_elf_sha256[32]={1}; };
inline const App *esp_app_get_description() { static App app;return &app; }
inline void (*shutdownHandler)()=nullptr;
inline int esp_register_shutdown_handler(void(*f)()) { shutdownHandler=f;return ESP_OK; }
struct Esp { unsigned restarts=0; void restart() { if(shutdownHandler)shutdownHandler();++restarts; } };
inline Esp ESP;
struct esp_timer_create_args_t { void(*callback)(void*)=nullptr;const char *name=nullptr; };
using esp_timer_handle_t=void*;
inline void(*timerCallback)(void*)=nullptr;
inline int esp_timer_create(const esp_timer_create_args_t *a,esp_timer_handle_t *p) { timerCallback=a->callback;*p=(void*)1;return ESP_OK; }
inline int esp_timer_start_periodic(esp_timer_handle_t,unsigned) { return ESP_OK; }
inline void advance(uint32_t now) { fakeMillis=now;timerCallback(nullptr); }
class BLECharacteristic;
class BLECharacteristicCallbacks { public: virtual ~BLECharacteristicCallbacks()=default;virtual void onWrite(BLECharacteristic*) {} };
class BLECharacteristic { public:
 static constexpr int PROPERTY_READ=1,PROPERTY_WRITE=2;
 String value; BLECharacteristicCallbacks *callback=nullptr;
 String getValue() { return value; }
 void setValue(const char *s) { value=s; }
 void setValue(const uint8_t *p,size_t n) { value.assign((const char*)p,n); }
 void setCallbacks(BLECharacteristicCallbacks *c) { callback=c; }
 void setAccessPermissions(int) {}
 void write(const void *p,size_t n) { setValue((const uint8_t*)p,n);callback->onWrite(this); }
};
class BLEService { public:
 std::map<String,BLECharacteristic*> chars;
 BLECharacteristic *createCharacteristic(const char *id,int) { return chars[id]=new BLECharacteristic; }
 void start() {}
};
struct ble_gap_conn_desc { unsigned conn_handle; };
class BLEServer;
class BLEServerCallbacks { public:
 virtual ~BLEServerCallbacks()=default;
 virtual void onConnect(BLEServer*) {}
 virtual void onConnect(BLEServer*,ble_gap_conn_desc*) {}
 virtual void onDisconnect(BLEServer*) {}
};
class BLEServer { public:
 BLEServerCallbacks *callback=nullptr; BLEService service;
 void setCallbacks(BLEServerCallbacks *c) { callback=c; }
 void updateConnParams(unsigned,int,int,int,int) {}
 BLEService *createService(const char*) { return &service; }
 void startAdvertising() {}
};
class Advertising { public:void addServiceUUID(const char*) {} void setScanResponse(bool) {} };
class BLEDevice { public:
 inline static BLEServer server;
 static void init(const char*) {} static void setMTU(int) {}
 static BLEServer *createServer() { return &server; }
 static Advertising *getAdvertising() { static Advertising a;return &a; }
 static void startAdvertising() {}
};
class BLESecurity { public:static void setCapability(int) {} static void setAuthenticationMode(bool,bool,bool) {} };
constexpr int MBEDTLS_MD_SHA256=1, U_FLASH=0;
inline const void *mbedtls_md_info_from_type(int) { return nullptr; }
inline int mbedtls_md_hmac(const void*,const uint8_t *key,size_t kn,const uint8_t *data,size_t n,uint8_t *out) {
 unsigned written=0;return HMAC(EVP_sha256(),key,int(kn),data,n,out,&written) && written==32 ? 0 : 1;
}
struct mbedtls_sha256_context { std::vector<uint8_t> data; };
inline void mbedtls_sha256_init(mbedtls_sha256_context *c) { c->data.clear(); }
inline void mbedtls_sha256_free(mbedtls_sha256_context *c) { c->data.clear(); }
inline int mbedtls_sha256_starts(mbedtls_sha256_context *c,int) { c->data.clear();return 0; }
inline int mbedtls_sha256_update(mbedtls_sha256_context *c,const uint8_t *p,size_t n) { c->data.insert(c->data.end(),p,p+n);return 0; }
inline int mbedtls_sha256_finish(mbedtls_sha256_context *c,uint8_t *out) { return SHA256(c->data.data(),c->data.size(),out)?0:1; }
inline int mbedtls_sha256(const uint8_t *p,size_t n,uint8_t *out,int) { return SHA256(p,n,out)?0:1; }
struct Updater {
 bool active=false;
 bool begin(uint32_t,int) { active=true;return true; }
 void abort() { active=false; }
 size_t write(const uint8_t*,size_t n) { return active?n:0; }
 bool end() { active=false;return true; }
};
inline Updater Update;
