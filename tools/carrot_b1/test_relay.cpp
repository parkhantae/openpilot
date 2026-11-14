#include "CarrotB1Relay/B1Relay.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <random>
using namespace b1relay;
Request req(uint32_t now, uint16_t seq, uint8_t op, uint8_t ttl=70) {
  return {42, now, seq, op, ttl};
}
int main(int argc, char**) {
  Controller c; c.connect(42, 0);
  if (argc > 1) { // Persistent production-controller harness for Python host tests.
    char op; uint32_t now, sid, stamp; unsigned seq, code, ttl;
    while (std::cin >> op >> now) {
      if (op == 'R') {
        std::cin >> sid >> stamp >> seq >> code >> ttl;
        c.accept({sid, stamp, uint16_t(seq), uint8_t(code), uint8_t(ttl)}, now);
      } else if (op == 'C') { std::cin >> sid; c.connect(sid, now); }
      else c.tick(now);
      std::cout << unsigned(c.mask) << ' ' << c.ack << ' ' << c.lastSeq << ' '
                << c.fault << ' ' << c.reason << std::endl;
    }
    return 0;
  }
  assert(!c.mask && !c.ack);
  assert(c.accept(req(99,1,Left),99) && !c.mask);
  assert(c.accept(req(100,2,Left),100) && c.mask==1 && c.ack==2);
  c.tick(349); assert(c.mask==1);
  c.tick(350); assert(!c.mask && c.ack==2);
  c.tick(450); assert(!c.ack && !c.leased);
  assert(c.accept(req(450,3,Right),450) && c.mask==2);
  assert(c.accept(req(451,4,Stop),451) && !c.mask && !c.ack);
  c.accept(req(550,5,Left),550); assert(!c.mask);
  c.accept(req(551,6,Left),551); assert(c.mask==1);
  c.accept(req(600,7,HoldLeft),600); assert(c.held && c.started==551);
  c.accept(req(601,8,Lease),601); assert(!c.mask && !c.ack);
  c.accept(req(701,9,Left),701); c.accept(req(702,10,Right),702);
  assert(!c.mask && c.fault);
  c.accept(req(900,11,HoldRight),900); assert(!c.mask && c.fault);
  c.connect(0,901); c.connect(42,902); assert(c.fault);
  c.accept(req(903,1,Stop),903); assert(!c.fault);
  c.accept(req(1003,2,Right),1003); c.accept(req(1004,3,HoldLeft),1004);
  assert(!c.mask && c.fault);
  c.accept(req(1104,4,Stop),1104); c.accept(req(1105,5,Right),1105);
  c.connect(0,1106); assert(!c.mask && !c.ack && !c.leased);
  assert(!c.accept(req(1107,6,Left),1107));
  c.connect(42,1108);
  c.accept(req(1206,1,Left),1206); c.accept(req(1207,2,HoldLeft),1207);
  for (uint32_t t=1250; t<11206; t+=50) {
    c.accept(req(t,uint16_t(3+(t-1250)/50),HoldLeft),t);
    assert(c.mask==1 && !c.fault);
  }
  c.tick(11206); assert(!c.mask && c.fault);
  c.accept(req(11207,300,HoldLeft),11207); assert(!c.mask && c.fault);
  c.accept(req(11208,301,Left),11208); assert(!c.mask && c.fault);
  c.accept(req(11209,302,Stop),11209); assert(!c.mask && !c.fault);
  c.accept(req(11306,303,Right),11306); assert(c.mask==2);
  // A valid lease can never extend the absolute 10-second limit.
  // Invalid input/replays do not change the active deadline or last sequence.
  auto deadline=c.deadline;
  auto r=req(11307,304,HoldRight); r.session=43;
  assert(!c.accept(r,11307)); assert(c.deadline==deadline && c.lastSeq==303);
  assert(!c.accept(req(11307,303,Stop),11307)); assert(c.mask==2);
  assert(!c.accept(req(11308,304,Left,0),11308));
  assert(!c.accept(req(11308,304,Left,71),11308));
  assert(!c.accept(req(11308,304,6),11308));
  assert(!c.accept(req(11309,304,Left),11308)); // future timestamp
  assert(!c.accept(req(11308,304,Left),11658)); // exact TTL expiry
  assert(!c.mask);
  // Sequence and millisecond wraparound.
  c=Controller{}; c.connect(42,0); c.lastSeq=65534;
  c.accept(req(0xfffffff0U,65535,Left),0xfffffff0U); assert(c.mask==1);
  c.accept(req(0x20,1,HoldLeft),0x20); assert(c.mask==1 && c.held);
  c.tick(0x20+350); assert(!c.mask);
  // Long randomized run checks exclusion, absolute cutoff and revocation.
  std::mt19937 rng(6174); uint32_t now=0xfffff000U;
  c=Controller{}; c.connect(42,now); unsigned n=0;
  for (int i=0;i<500000;++i) {
    now += rng()%80;
    if (rng()%17==0) c.connect((rng()%2)?42:0,now);
    else if (rng()%3) {
      auto q=req(now,uint16_t(++n),rng()%8,uint8_t(rng()%75));
      if (rng()%5==0) q.stamp-=400;
      c.accept(q,now);
    } else c.tick(now);
    assert(c.mask==0 || c.mask==1 || c.mask==2);
    if (c.mask) {
      assert(c.session && c.leased && !c.fault);
      assert(now-c.started<MAX_ON_MS && int32_t(c.deadline-now)>0);
    }
    if (!c.session) assert(!c.mask);
  }
  std::cout << "relay controller: boundary cases and 500000 randomized steps passed\n";
}
