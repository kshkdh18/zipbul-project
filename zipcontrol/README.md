# Zipcontrol · Astra 계획 + Luna Decisions 조작

Android 드론 앱의 조이스틱을 직접 조작하는 카메라 기반 드론 제어 Mac 앱입니다. **선택한 카메라 영상 → Astra 하위 목표 → Luna 동작 선택 → Android 조이스틱 터치 → 기체 이동 → 새 영상**을 반복하며, 수락된 명령으로 3D 이동 가이드를 표시합니다.

**실제 드론 비행 제어를 확인했습니다.** 2026-10-10 사용자 확인과 [비행 데모 영상](https://www.youtube.com/watch?v=CwKV0vJf2Jg)을 근거로 검증 기록을 보완했습니다. 영상의 [3:55](https://www.youtube.com/watch?v=CwKV0vJf2Jg&t=235s)와 [4:09](https://www.youtube.com/watch?v=CwKV0vJf2Jg&t=249s)에서 실제 기체가 공중에 떠 있고 Zipcontrol 실행 화면이 함께 보입니다. 기존 관찰 전용 세션·Chrome 터치 진단과 비행 데모의 근거는 [VALIDATION.md](VALIDATION.md)에 구분해 기록했습니다.

사람이 기체를 손으로 들고 이동하는 시연도 지원합니다. 아래 실행 순서는 이 시연 방식에 해당하며, 현재 모델 프롬프트에도 손으로 들고 이동한다는 전제가 남아 있습니다. 이번 문서 정정은 실제 비행 확인 결과를 추가한 것으로, 제어 코드나 프롬프트 변경을 포함하지 않습니다.

## 실행

```sh
cd /Users/ksh/zipbulProject/zipcontrol
uv sync --frozen
uv run --frozen python android/build.py
uv run zipcontrol
```

Python 3.12–3.13, Java 17, Android SDK platform 36/build-tools 36.0.0과 ADB가 필요합니다. SDK 기본 위치는 `~/Library/Android/sdk`이며 `ANDROID_HOME`으로 변경할 수 있습니다. 서버 빌드는 고정된 scrcpy 4.1 소스와 체크섬을 사용하며 시스템 scrcpy를 변경하지 않습니다. 원본 JipbulProject 폴더는 실행에 필요하지 않습니다.

`OPENAI_API_KEY`를 환경변수 또는 이 폴더의 `.env.local`에 설정하세요. 앱 자체는 다른 프로젝트에서 키·로그·검증 기록을 자동으로 가져오지 않습니다. AI 실행 시 선택한 이미지와 목표가 OpenAI API로 전송되고 사용량이 발생합니다. Astra는 Responses의 `gpt-6-astra`, Luna는 Decisions의 `gpt-6-luna`를 사용합니다. SDK는 `openai>=3.26,<4`입니다.

## 언어 설정 / Language

**Options → Language**에서 **English / 한국어**를 선택합니다. 기본 언어는 영어입니다. 버튼·보정 안내·상태 메시지·3D 방향과 범례가 즉시 바뀌며 `.runtime/settings.json`에 선택을 저장합니다. 언어 변경은 입력한 목표, USB 연결, 보정, 제어 설정이나 진행 중인 임무를 초기화하지 않습니다. AI가 작성하는 하위 목표·완료 조건·설명은 다음 임무부터 선택한 언어를 사용하며 사용자가 입력한 목표는 그대로 보존합니다.

Choose **English** or **한국어** in **Options → Language**. English is the default. The interface updates immediately and the preference is remembered. AI descriptions use the selected language from the next mission; your goal and control settings are preserved.

## 손으로 들고 이동하는 시연 순서

1. 잠금을 해제한 Android를 USB로 연결하고 USB 디버깅을 승인합니다. 기존 DJI 앱에서 카메라와 조이스틱이 있는 화면을 엽니다.
2. **AI 전용 서버 → USB 연결**을 누릅니다. 연결만으로 입력을 보내지 않습니다.
3. **기존 L/R 보정 가져오기**에서 예전 `calibration.json`을 선택합니다. 기기와 영상 크기가 맞는 보정만 적용됩니다. 또는 현재 화면에서 중심·반경을 직접 보정합니다.
4. **AI 목표 수행 → 카메라 영역 지정**에서 영상의 두 모서리를 클릭합니다. 아래의 **AI가 보는 영상**으로 UI가 제외됐는지 확인합니다. 이 영역은 기기·화면 크기별로 저장됩니다.
5. 목표를 입력하고 실행 방식을 선택한 뒤 **AI 임무 시작 · 실제 입력**을 누릅니다. 기본은 **Astra 계획 + Luna 조작**입니다. 큰 한글 지시와 화살표를 보며 기체를 손으로 이동합니다. 단순한 시각 목표에는 **Luna 직접 실행**도 선택할 수 있습니다.
6. **Esc / 일시 중단 / 임무 종료**로 터치를 해제합니다. 임무 도중 카메라 영역을 다시 지정하면 기존 판단을 폐기하고 새 영역으로 계속합니다.

카메라 영역을 지정하지 않으면 시작할 수 없고 전체 화면으로 대체하지 않습니다. 현재·이전 비교 이미지 모두 크롭해서 전달합니다. 화면 세션·크기가 변경되면 다시 보정하고 영역을 지정합니다. 모델은 이륙 상태 UI를 받지 않으며, 사람이 기체를 들고 이동한다고 안내됩니다. 이륙·착륙 버튼은 자동으로 누르지 않습니다.

## 화면과 동작

- 초록 화살표는 전후, 파랑은 좌우, 노랑은 상하, 보라 곡선은 회전입니다. 방향은 기체/카메라 기준입니다. 3D 화면을 드래그하면 시점을 회전하고 휠로 확대합니다. 더블클릭으로 기본 시점을 복원합니다.
- 가상 궤적은 **Android가 수락한 명령**으로만 계산합니다. 실제 기체 위치·속도·거리 측정값이 아닙니다. 기본 이동은 1 가상 단위/초, 회전은 45도/초이며 입력 크기에 비례합니다.
- 수동 버튼과 AI 명령은 같은 실행 이벤트를 사용합니다. 기본 드래그 크기는 100%이며 5–100%로 조절할 수 있습니다. Luna는 방향만 선택하고 앱이 축 설정에 맞는 스틱 좌표와 2,000ms 유효 시간을 적용합니다. 사용하지 않는 스틱은 해제합니다.
- 명령당 최대 2초이며 만료 시 터치와 가상 이동이 멈춥니다. 마지막 지시는 다음 판단까지 남습니다. API 판단은 별도 스레드에서 실행되고 3D 렌더링과 Android 갱신을 막지 않습니다.
- **관찰 전용**은 선택 사항입니다. 이 모드에서는 실제 터치나 가상 이동 없이 모델의 제안만 표시합니다.
- 사전 검증 기록, 5분 임무 제한, 화면 픽셀 유사도 검사, Mac 포커스에 따른 AI 중단은 없습니다. 수동 버튼은 놓기·포커스 상실 시 해제합니다.
- 연결 단절, 영상 지연, 좌표계 변경, Android 대상 앱 변경, 잘못된 명령에는 입력을 해제합니다. heartbeat는 이동 시간을 연장하지 않습니다. 늦은 응답과 중복 관찰은 다시 실행하지 않습니다.

## Astra와 Luna의 역할

- Astra는 임무 시작, 하위 목표 완료, 재계획, 카메라 영역 변경 때만 계획합니다. 현재 하위 목표·완료 조건·허용 동작을 만들고 계획 중에는 터치를 해제합니다.
- Luna는 최신·이전 카메라 크롭, 하위 목표, 현재 입력과 연속 유지 시간, 최근 실행 결과로 하나의 `next_action`을 선택합니다. 임무당 요청은 하나씩, 최소 200ms 간격으로 보내며 새로운 프레임이 필요합니다.
- 8개 이동 enum은 좌우 회전, 상하, 좌우 이동, 전후입니다. `WAIT`는 해제 후 재관찰, `SUBGOAL_DONE`은 영상으로 완료 검토, `REPLAN`은 해제 후 Astra 재계획입니다. 직접 모드의 `REPLAN`도 계층형으로 전환합니다.
- 새 응답이 수락되면 기존 입력을 연속 갱신합니다. Luna 관찰에서 2초가 지난 응답, 이전 세션·계획·영역의 응답, 만료 전에 시작된 응답은 실행하지 않습니다. API 오류와 refusal은 해제 후 오류 표시하며 자동 재시도하지 않습니다.
- 전체 완료는 입력 해제 후 최소 0.5초 간격의 새 영상 두 장에서 추가 확인합니다. 계층형은 Astra, 직접 모드는 Luna가 확인합니다.
- confidence는 진단용이며 드래그 크기나 실행 여부를 임의의 임계값으로 바꾸지 않습니다. 가상 궤적을 실제 이동·완료 근거로 모델에 제공하지 않습니다.

프롬프트는 `src/zipcontrol/planning.py`의 `CONTEXT`, `PLANNER_SYSTEM`, `PLANNER_TOOLS`, `luna.py`의 `LUNA_SYSTEM`, `actions.py`의 `ACTION_DESCRIPTIONS`, `STATUS_ACTIONS`에서 수정합니다. `astra.py`의 `SYSTEM`은 비교용 기존 Astra 단독 조작에만 사용합니다.

## 개발과 검증

```sh
uv run --frozen pytest -q
uv run --frozen ruff check src tests tools android/build.py
uv build
QT_QPA_PLATFORM=cocoa uv run --frozen python tools/render_preview.py
```

마지막 명령은 실제 Mac Qt 3D 화면을 합성 입력으로 렌더링해 `artifacts/ui-preview/`에 저장합니다. Android와 API에는 연결하지 않습니다.

USB 휴대폰의 Chrome 진단 페이지에서 **실제 두 포인터 → 공통 실행 이벤트 → Mac 3D → 2초 만료**를 함께 확인하려면 `QT_QPA_PLATFORM=cocoa uv run python tools/verify_device_path.py`를 실행합니다. 결과와 화면은 `artifacts/device-display/`에 저장합니다. 이 검사는 DJI 조이스틱을 조작하거나 API를 호출하지 않습니다.

실기 진단은 `uv run zipcontrol validate-guard`, 물리 USB 분리 진단은 `uv run zipcontrol validate-usb`입니다. 두 진단은 휴대폰 Chrome 테스트 화면을 열며 실행의 사전 조건은 아닙니다. `benchmark-astra`는 현재 Android 화면에서 **저장한 카메라 영역만** 관찰하며 기본 20회 API를 호출합니다. 앱을 전환하거나 터치를 보내지 않습니다.

`artifacts/mission-*/`에 크롭 이미지, 판단·실행 이벤트, Android ACK, 종료 보고서를 기록합니다. 공통 이벤트의 `command_id`는 앱 세션 순번이고 `android_command_id`는 서버 응답 ID입니다. `.runtime/`과 `calibration.json`은 개인 설정이며 Git에서 제외합니다. 검증 범위와 미확인 사항은 [VALIDATION.md](VALIDATION.md)를 참고하세요.

Luna 추가 검증:

```sh
# 같은 저장 카메라 크롭으로 모델별 20회 비교, 실제 터치 없음
uv run zipcontrol benchmark-luna --samples 20
# 이미 잘라진 합성 카메라 파일로 비교
uv run zipcontrol benchmark-luna --image artifacts/ui-preview/camera.png --samples 20
# 실제 API로 좌/우/상/하/중앙 합성 이미지 판정 (5회)
uv run python tools/evaluate_luna_camera.py
# 실제 Android Chrome에서 8개 enum의 좌표·화살표 계산·만료 검증 (API 없음)
uv run python tools/verify_luna_device.py
# USB와 목표를 준비한 일반 GUI에서 사용자가 시작·중단하는 시연
QT_QPA_PLATFORM=cocoa uv run python tools/handheld_demo.py --goal '지금 보이는 공간의 가장자리를 따라 탐색해'
```

벤치마크는 이미지와 목표를 고정하지만 Astra는 함수 인자, Luna는 enum을 반환하므로 서로 다른 계약을 비교합니다. 지연·오류와 동작 일치율을 함께 읽어야 하며 실제 임무 성공률은 아닙니다. `model_metrics`에 Astra/Luna 호출 수·오류·p50/p95, 실행 기록에 세션·계획 버전·관찰 ID·선택 enum·Android ACK를 연결합니다.

`not armed`로 중단된 경우 임무의 `events.jsonl`에서 `guard_diagnostics.first_disarm`을 확인합니다. heartbeat 만료·대상 앱 변경·전경 감시 오류 등 최초 해제 원인을 후속 오류와 구분해 보존합니다. `handheld_demo.py`는 입력 중 창 캡처를 생략해 통신 스레드 지연을 줄입니다. 중단 후 자동으로 입력을 재개하지 않으며 원인을 확인한 뒤 새 임무를 시작합니다.

## 구조

`camera`가 크롭과 영역 저장, `planning`이 Astra 계획, `luna`가 Decisions 호출, `actions`가 enum 변환, `guidance`가 계층 제어를 담당합니다. `mission.Executor`의 독립된 실행 루프와 `execution`의 공통 이벤트는 그대로 사용합니다. `simulation`은 렌더러와 분리된 가상 이동 계산이며 `sim_view`와 `qml/`이 Qt Quick 3D 화면을 구성합니다. `android/`와 `guard`는 기존 `jipbul-guard-4` 전송 계약을 보존합니다.

빌드한 scrcpy 서버의 Apache-2.0 라이선스는 `artifacts/android/SCRCPY-LICENSE`에 보존됩니다. 참고: [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions), [OpenAI 함수 호출](https://developers.openai.com/api/docs/guides/function-calling), [Qt Quick 3D](https://doc.qt.io/qt-6.11/qml-qtquick3d-view3d.html).
