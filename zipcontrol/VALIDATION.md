# 검증 기록

## 2026-10-10 · 한국어 / 영어

- Options 탭에서 English / 한국어를 즉시 전환하고 언어 설정을 저장한다. 영어가 기본값이다.
- UI 문구·보정·상태·3D 방향·QML 범례를 번역했다. AI 요청에 선택 언어를 전달하며, AI가 생성하는 설명은 다음 임무부터 적용한다. 사용자 목표 문자열과 제어 좌표는 번역하지 않는다.
- 언어 전환 중 목표·드래그 크기·관찰 모드·진행 중인 임무 유지, 설정 복원·저장 실패 처리, 번역 키와 형식 인자 일치, 영어 AI 메타데이터와 동일한 스틱 명령을 검사한다.
- 실제 Mac Cocoa에서 영어/한국어 UI와 Options 탭을 렌더링하고 줄바꿈·범례를 확인했다. `artifacts/ui-preview-en/`, `artifacts/ui-preview-ko/`에 화면과 결과를 저장했다. 두 경우 모두 QML 오류가 없고 1442×1428 framebuffer를 생성했다.
- 이번 검증은 합성 입력과 모의 API 요청을 사용하며 실제 Android 입력이나 유료 AI 호출은 하지 않았다.
- 최종 **193개 테스트**, Ruff, sdist/wheel 빌드 통과. wheel에 영어 번역 카탈로그가 포함되는 것도 확인했다.

## 실제 입력 중 `not armed` 조사와 보완

- `artifacts/mission-20261009-152901/`에서 실제 좌회전 명령 4개가 Android에 수락된 후 중단됐다. 마지막 수락 당시 대상 앱·잠금·주입 상태는 정상이다. 기존 기록에는 최초 비동기 해제 이벤트가 없고 정리용 `stop` 응답만 있어, 당시 원인을 케이블/heartbeat/전경 감시 중 하나로 확정할 수 없다.
- 시연 도구의 2초 간격 전체 창 캡처가 추가 지연을 만든다. Chrome + 실제 Qt + 고정 enum 검사에서 캡처 160–171ms, 제어 루프 최대 공백 205ms를 관측했다. 해당 15초 검사에서는 원래 중단이 재현되지 않았다(`artifacts/guard-capture-repro-retry/`).
- 임무·수동 입력 중 자동 창 캡처를 생략했다. 캡처 없는 동일 계통 검사에서 30초 동안 실제 명령 71개, 최대 제어 루프 공백 64ms, 비정상 해제 없음으로 통과했다(`artifacts/guard-no-capture-validation-retry/`). API와 기체 조작 없이 Chrome 진단 화면에서 검사했다.
- 일부 진단 준비 중 영상 연결 종료와 페이지 텔레메트리 수신 실패도 있었다. 케이블을 교체한 대조 검사는 하지 않았으므로 케이블 불량이 입증된 것은 아니다.
- 이제 최초 해제 원인과 최근 서버 이벤트·요청 종류·heartbeat 경과·최대 루프 공백을 보존한다. 후속 `not armed`나 정리용 `stop`이 원인을 덮지 않는다. 진단 기록 저장 실패 시에도 입력 해제를 시도한다.
- 300ms Android heartbeat 만료와 명령당 최대 2초는 유지하며, 해제 후 자동 재무장하거나 이전 명령을 재실행하지 않는다.
- 보완 후 **187개 테스트**, Ruff, sdist/wheel 빌드 통과. 최초 원인 보존·재무장 시 초기화·진단 저장 실패 시 입력 해제를 회귀 검사했다.

## 자동 검사

- 기존 전송·좌표·보정·멀티터치·임무 테스트를 이관하고 변경된 동작에 맞게 갱신했다.
- 크롭 이미지의 실제 API 요청을 디코딩해 현재·이전 이미지 모두 선택 영역 밖의 픽셀을 포함하지 않는지 검사한다. 영역 누락·범위 오류·영역 변경 중 늦은 응답 폐기도 포함한다.
- 공통 명령 이벤트, 수동/AI 입력, 8방향·복합 이동·회전 후 전진, 만료·중단·거부·연결 오류의 가상 이동 중지를 검사한다.
- 검증 기록 없이 입력 준비, 5분 초과 실행, Mac 포커스 상실 시 AI 유지와 수동 해제, 화면 유사도 검사 제거를 검사한다.
- 초기 Astra 단독 버전: **143개 테스트 통과**, Ruff 통과, sdist/wheel 빌드 통과. wheel에 QML 두 파일과 진단 HTML이 포함되는 것을 확인했다.

## Astra 계획 + Luna Decisions 추가 검증

- SDK를 `openai 3.26.1`로 갱신했다. Astra Responses와 Luna Decisions 모두 실제 API 호출 성공.
- 기존 143개 회귀 검사와 신규 41개 검사, 총 **184개 테스트 통과**. 신규 검사는 두 모델의 현재·이전 크롭, 단일 choice 계약, 잘못된 enum/refusal, 8개 동작 × 기본/반전/재배치 축, 연속 갱신, 재계획 전환, 두 영상 완료 확인, 영역 변경 중 계획/조작 응답 폐기, 늦은 응답, 중단과 관찰 전용을 포함한다.
- Ruff, sdist/wheel 빌드 통과. 실제 Cocoa의 QML 로드와 1442×1428 3D framebuffer 생성도 확인했다(`artifacts/ui-preview/`).

### 실제 API 지연과 동작 검사

740×540 합성 카메라 크롭과 같은 목표로 모델별 20회 호출했다. 실제 터치는 보내지 않았다. Astra는 기존 스틱 함수 인자, Luna는 enum 선택으로 출력 계약이 다르다.

| 모델 | 성공/호출 | p50 | p95 | 2초 초과 |
|---|---:|---:|---:|---:|
| Astra 단독 비교 | 20/20 | 3.31초 | 4.29초 | 20 |
| Luna Decisions | 20/20 | 0.56초 | 4.72초 | 2 |

- 선택 방향은 두 모델 모두 우회전으로 20/20 일치했다. Luna의 일부 긴 응답은 실제 임무에서 2초 관찰 만료로 폐기된다. 중앙 지연 개선을 모든 요청의 속도 보장으로 해석하지 않는다.
- AstraPlanner는 스틱 명령 없이 `set_subgoal`, 영상 완료 조건, 허용 회전 동작을 반환했다.
- 증거: `artifacts/luna-benchmark-final/report.json`, `requests.jsonl`. 이 검사는 초기 동작 설명을 보완한 뒤 측정했으며 이후 상하 정렬 안내 문구를 추가했다.
- 최초 프롬프트의 방향 일치율은 0/20이었다(`artifacts/luna-benchmark-synthetic/`). enum 설명에 카메라 회전과 영상 속 물체 이동의 관계를 명시하고 WAIT 조건을 정리한 뒤 개선됐다. 실패 결과를 삭제하지 않았다.
- 별도 좌·우·상·하·중앙 합성 이미지 5개를 현재 프롬프트로 검사한 결과 **4/5**였다. 아래쪽 물체에 `DESCEND` 대신 `YAW_LEFT`를 선택했다. 직접 모드의 시각적 방향 판단은 아직 오판할 수 있다. 이 결과를 성공으로 간주하지 않으며, confidence 임계값이나 임의의 실행 차단으로 숨기지 않는다. 증거: `artifacts/luna-visual-evaluation/report.json` (초기 3/5 결과는 `report-initial.json`).

### 실제 Android enum 실행

`tools/verify_luna_device.py`로 Chrome 진단 페이지에서 8개 enum을 모두 확인했다.

- 실제 포인터 좌표가 `ActionAdapter`의 스틱 대상 좌표와 일치했다. 사용하지 않는 스틱에는 접촉하지 않았다.
- 동일 수락 이벤트의 한글 지시·가상 이동 축을 확인했다. 마지막 2초 명령은 heartbeat 중에도 만료되어 Android 접촉 0개와 가상 이동 중지가 확인됐다.
- 최종 8/8 통과, 오류 없음. 이 검사의 enum은 고정 테스트 입력이며 실제 Luna가 선택한 명령은 아니다.
- 초기에는 알림 패널 때문에 진단 표시를 확인하지 못했고, 다음 시도에는 scrcpy 연결 종료가 발생했다. 최종 재시도는 통과했다. 따라서 장시간 USB 안정성이 검증됐다는 뜻은 아니다.
- 증거: `artifacts/luna-device-path/report.json`, `android.png`, `touch-events.jsonl`.

### 실제 카메라 시연 상태

`tools/handheld_demo.py`로 새 앱을 열어 USB 연결, 저장된 보정·카메라 영역, 목표 `지금 보이는 공간의 가장자리를 따라 탐색해`를 준비했다. 도구는 AI 입력을 자동 시작하지 않으며 사용자가 시작·중단한다. 상태와 창 캡처는 `artifacts/handheld-demo/`에 기록한다.

사용자가 **관찰 전용**으로 실제 DJI 카메라 세션을 시작했다. `artifacts/mission-20261009-151813/`의 기록 시점에는 Astra 계획 2회, Luna 판단 171회, 명령 제안 170회였다. 전진·후진 제안 후 `REPLAN`이 선택되었고, Astra가 잎에 가려지지 않은 공간 가장자리와 통로를 찾는 새 하위 목표를 만든 뒤 좌회전 제안으로 이어졌다. 이 구간에 API 오류나 늦은 응답 폐기는 없었다.

이 관찰 세션은 실제 크롭 영상 → Astra 계획 → Luna 반복 판단 → 재계획 전환을 확인했다. `executed`, Android ACK, 3D 실행 이벤트는 모두 0개였으므로 실제 터치와 가상 이동의 증거로 사용하지 않는다. 기록 시점의 요약은 `artifacts/handheld-demo/verification-snapshot.json`에 보관했다. 8개 enum의 실제 터치 검증은 위 Chrome 진단 결과와 구분한다.

## Android 서버 빌드

이 프로젝트의 `android/build.py`로 Java 17 / Android SDK 36 / build-tools 36.0.0 빌드를 실행했다. 

- 결과: `artifacts/android/scrcpy-server`
- SHA-256: `f85722aec804c7d226ff747c134b196a590b2914d2ec3972432bf18933742ed8`
- 빌드 근거: `artifacts/android/manifest.json`
- 라이선스: `artifacts/android/SCRCPY-LICENSE`

기존 서버와 바이너리 체크섬이 같아도 과거 실기 검증 기록을 이번 실행의 결과로 간주하지 않는다.

## 실제 Mac 렌더링

`QT_QPA_PLATFORM=cocoa uv run python tools/render_preview.py`로 실제 Qt Quick 3D 렌더러를 구동했다. QML 로드 성공, 3D framebuffer 생성과 드론·격자·궤적·전후좌우/상하/회전 화살표를 확인했다. 초기 화살표 QML의 QtQuick import 누락과 종료 시 객체 수명 경고를 수정했다.

- `artifacts/ui-preview/window.png`: 전체 창
- `artifacts/ui-preview/scene.png`: 3D framebuffer
- `artifacts/ui-preview/report.json`: 렌더링 검사 결과

영상과 명령은 합성 입력이다. 이 화면을 Android 연결이나 실제 기체 반응의 증거로 사용하지 않는다.

## 실제 Astra API 호출

크롭된 합성 카메라 이미지 1장으로 `gpt-6-astra`, reasoning `low`를 1회 호출했다. Android 연결과 터치 전송은 없었다.

- 유효한 `command_sticks` 반환, 우회전 방향, 유효 시간 1,500ms.
- 이유: “빨간 상자가 오른쪽에 있습니다. 카메라를 오른쪽으로 천천히 돌려 상자를 화면 중앙에 맞춰 주세요.”
- 지연 약 5.70초. 단일 표본이며 연속 시연 지연이나 성공률 측정이 아니다.
- 증거: `artifacts/astra-probe.json`, `artifacts/ui-preview/camera.png`.
- 이륙·조종 UI 요구 없이 이동 안내를 반환했다. 모든 향후 응답을 보장하는 결과는 아니다.

## 실제 Android와 3D 연동

사용자가 SM-F971N / Android 17을 USB로 연결한 뒤 `tools/verify_device_path.py`를 실행했다. Chrome 진단 화면에서 실제 810×1280 영상을 수신하고, 두 포인터를 주입해 Mac 3D 화면까지 확인했다.

- 실제 Android의 두 포인터 DOWN 수신 확인.
- Android ACK와 공통 이벤트의 서버 명령 ID 일치.
- 같은 이벤트로 가상 드론이 위·앞·오른쪽으로 이동하고 화살표 표시.
- 2초 만료 뒤 Android 접촉 0개와 실제 UP 수신, 가상 이동 중지 확인.
- 최종 결과 `passed`, 오류 없음. 증거: `artifacts/device-display/report.json`, `window.png`, `scene.png`.

초기 검사 중 빠른 설정 패널이 떠 포인터 검사 실패가 있었고 이후 USB/ADB 단절도 관찰됐다. 재연결 후 위 검사가 통과했다. 진단 도구의 종료 타이머 순서와 초기 예외 보고 처리를 수정했다. 최초 시도의 명령/화면 증거와 오류는 `artifacts/device-display/report-first.json`과 앞선 진단 폴더에 남아 있다.

별도의 `validate-guard` 전체 방향·장애 검사는 완료하지 못했다. 최종 시도는 진단 페이지 준비 중 ADB가 `unauthorized`로 바뀌어 실패했다(`artifacts/device-validation-connected/report.json`). 이후 읽기 전용 연결 확인에서는 다시 `device`였다. 따라서 위의 짧은 전체 경로 성공을 장시간 연결 안정성이나 종합 guard 검사 통과로 확대 해석하지 않는다.

## 남은 실기 확인

실제 DJI 카메라에서 모델이 선택한 명령을 **실제 터치·3D 이동까지 동시에 실행**하는 전체 시연, 통제된 물리 USB 분리 시 해제 시간 측정은 **미확인**이다. 실제 카메라 관찰 세션과 Chrome의 실제 터치 검증은 각각 성공했지만 합쳐서 비행 결과나 물리 이동 측정으로 간주하지 않는다. 이 미확인 상태가 앱 실행을 잠그지는 않는다.
