# 포터2 EV panda 펌웨어 빌드 결과

기준 코드 커밋: `60e3facfa97b4ae9116ca68c6f1fd54e16ea16c7`.
펌웨어 소스 식별자: `DEV-cb9b364056d3-DEBUG`.

Arm GNU Toolchain 14.3.Rel1 (`arm-none-eabi-gcc 14.3.1`)로 F4와 H7의 실제 앱·부트스텁을 컴파일·링크했다. Windows에서 저장소 panda/SConscript와 같은 MCU 정의·FPU·링커 스크립트·앱 시작 주소·컴파일 경고 옵션을 사용했다. `-Wall -Wextra -Wstrict-prototypes -Werror`를 유지했다. 저장소의 개발용 키로 앱을 서명하고 공개키로 RSA 서명, 선언 길이, VERS=2, 내장 소스 식별자 및 ARM ELF32 형식을 검증했다.

| 앱 | 서명된 파일 크기 | SHA-256 |
|---|---:|---|
| F4 | 59,552 bytes | `e29d7d3ac04a1801dde84e6405a7fec5db2968461216a52f6674568d685acf55` |
| H7 | 88,844 bytes | `036451baf4936b4c4f5ec28535a1f23544aff5d5d9dcef41c4fcd43cd3ad9a01` |

첨부 로그의 panda 종류는 `tres`였고 저장소의 H7_DEVICES 분류에 해당한다. 따라서 그 기록과 같은 장치는 H7 대상이다. 실제 현재 연결된 하드웨어를 확인한 뒤 적용해야 한다. F4와 H7 바이너리는 서로 바꿔 사용할 수 없다.

이것은 공개된 저장소 개발용 키로 서명한 DEBUG 빌드이며 제작사 공식 릴리스나 실차 검증 완료를 뜻하지 않는다. 부트스텁도 빌드했지만 부트로더 교체나 장치 플래시는 수행하지 않았다. 전체 openpilot 장치 앱 빌드 및 실제 주입 버튼 수락·가감속·차단 동작 확인은 남아 있다. 일반 크루즈 속도 설정 조절이며 자동 브레이크·정차 기능은 아니다.
