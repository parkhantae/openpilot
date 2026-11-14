#include "CarrotB1Relay/CarrotB1Relay.ino"
#include <cassert>
#include <iostream>
void request(uint16_t seq, uint8_t op, bool valid=true, int32_t age=0, uint32_t sid=0) {
  Request r={sid?sid:relay.session, uint32_t(millis()-age), seq, op, 70, {}};
  uint8_t digest[32];
  mbedtls_md_hmac(nullptr,key,32,(uint8_t*)&r,offsetof(Request,tag),digest);
  memcpy(r.tag,digest,8); if(!valid) r.tag[0]^=1;
  BLEDevice::server.service.chars[CONTROL]->write(&r,sizeof(r));
  loop();
  assert(!pinConflict);
  assert(bool(pins[LEFT_GPIO])==(relay.mask==1));
  assert(bool(pins[RIGHT_GPIO])==(relay.mask==2));
}
int main() {
  uint8_t originalKey[32]; for(unsigned i=0;i<32;++i) originalKey[i]=i;
  prefs.putBytes("auth",originalKey,32);prefs.putBytes("owner-key",originalKey,32);
  setup();
  assert(claimed && !memcmp(key,originalKey,32)); // existing registration retained
  assert(!pins[LEFT_GPIO] && !pins[RIGHT_GPIO]);
  auto &server=BLEDevice::server;
  server.callback->onConnect(&server);
  advance(100);
  request(1,b1relay::Left,false); assert(!relay.mask && !relay.lastSeq);
  request(1,b1relay::Left,true,350); assert(!relay.mask && !relay.lastSeq);
  request(1,b1relay::Left,true,-1); assert(!relay.mask && !relay.lastSeq);
  request(1,b1relay::Left,true,0,relay.session+2); assert(!relay.mask && !relay.lastSeq);
  request(1,b1relay::Left); assert(relay.mask==1 && relay.ack==1);
  request(1,b1relay::Right); assert(relay.mask==1); // replay cannot switch
  advance(150);request(2,b1relay::HoldLeft);assert(relay.held);
  // Timer alone releases output during a stalled main loop / lost BLE commands.
  advance(499); assert(relay.mask==1);
  advance(500); assert(!relay.mask && !pins[LEFT_GPIO] && !pins[RIGHT_GPIO]);
  advance(600);request(3,b1relay::Right);assert(relay.mask==2);
  server.callback->onDisconnect(&server);
  assert(!relay.mask && !pins[LEFT_GPIO] && !pins[RIGHT_GPIO]);
  uint32_t old=relay.session;
  server.callback->onConnect(&server);assert(relay.session!=old);
  advance(700);request(1,b1relay::Right);assert(relay.mask==2);
  shutdownHandler();assert(!relay.mask && !relay.session);
  server.callback->onConnect(&server);
  advance(800);request(1,b1relay::Left);assert(relay.mask==1);
  request(2,b1relay::Stop);assert(!relay.mask && !relay.ack);
  advance(900);request(3,b1relay::Right);assert(relay.mask==2);
  request(4,b1relay::HoldRight);
  unsigned seq=5;
  for(unsigned t=950;t<10900;t+=50) { advance(t);request(seq++,b1relay::HoldRight);assert(relay.mask==2); }
  advance(10900);assert(relay.fault && !relay.mask && !pins[RIGHT_GPIO]);
  request(seq++,b1relay::HoldRight);assert(!relay.mask);
  request(seq++,b1relay::Stop);assert(!relay.fault);
  // OTA starts only with both outputs off and suppresses queued controls.
  advance(11000);
  uint8_t manifest[73]={4};
  uint32_t sid=relay.session,size=256;
  memcpy(manifest+1,&sid,4);memcpy(manifest+5,&size,4);
  mbedtls_md_hmac(nullptr,key,32,manifest,41,manifest+41);
  ota::attr->write(manifest,sizeof(manifest));loop();assert(ota::busy);
  request(seq++,b1relay::Left);assert(!relay.mask);
  server.callback->onDisconnect(&server);loop();assert(!ota::busy && !relay.mask);
  // Fresh v3 report describes outputs; it cannot claim physical lamp evidence.
  advance(11100);loop();Report report;
  assert(metaValue->value.size()==sizeof(report));memcpy(&report,metaValue->value.data(),sizeof(report));
  assert(report.version==3 && report.outputs==0);
  // Unclaimed boot cannot energize even with the UART recovery key.
  claimed=false; server.callback->onConnect(&server);
  advance(11200);request(1,b1relay::Left);assert(!relay.mask);
  request(1,b1relay::Stop);assert(relay.lastSeq==1);
  assert(!pinConflict);
  std::cout << "actual firmware loop: HMAC, session/replay, GPIO exclusion, STOP, timer cutoff, disconnect, shutdown, OTA, unclaimed OFF passed\n";
}
