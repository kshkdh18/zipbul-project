# Zipcontrol · Astra 이동 가이드

드론을 시연용 Mac 앱입니다. **선택한 카메라 영상 → Astra 이동 지시 → Android 실제 터치 + 3D 가이드 → 사람이 이동 → 새 영상**을 반복합니다.

## 실행

```sh
cd /Users/ksh/zipbulProject/zipcontrol
uv sync --frozen
uv run --frozen python android/build.py
uv run zipcontrol
```

Python 3.12–3.13, Java 17, Android SDK platform 36/build-tools 36.0.0과 ADB가 필요합니다. SDK 기본 위치는 `~/Library/Android/sdk`이며 `ANDROID_HOME`으로 변경할 수 있습니다. 서버 빌드는 고정된 scrcpy 4.1 소스와 체크섬을 사용하며 시스템 scrcpy를 변경하지 않습니다. 원본 JipbulProject 폴더는 실행에 필요하지 않습니다.

`OPENAI_API_KEY`를 환경변수 또는 이 폴더의 `.env.local`에 설정하세요. 앱 자체는 다른 프로젝트에서 키·로그·검증 기록을 자동으로 가져오지 않습니다. Astra 실행 시 선택한 이미지와 목표가 OpenAI API로 전송되고 사용량이 발생합니다.

## 시연 순서

1. 잠금을 해제한 Android를 USB로 연결하고 USB 디버깅을 승인합니다. 기존 DJI 앱에서 카메라와 조이스틱이 있는 화면을 엽니다.
2. **AI 전용 서버 → USB 연결**을 누릅니다. 연결만으로 입력을 보내지 않습니다.
3. **기존 L/R 보정 가져오기**에서 예전 `calibration.json`을 선택합니다. 기기와 영상 크기가 맞는 보정만 적용됩니다. 또는 현재 화면에서 중심·반경을 직접 보정합니다.
4. **Astra 목표 수행 → 카메라 영역 지정**에서 영상의 두 모서리를 클릭합니다. 아래의 **Astra가 보는 영상**으로 UI가 제외됐는지 확인합니다. 이 영역은 기기·화면 크기별로 저장됩니다.
5. 목표를 입력하고 **AI 임무 시작 · 실제 입력**을 누릅니다. 큰 한글 지시와 화살표를 보며 기체를 손으로 이동합니다. Astra는 새 영상으로 자동 판단합니다.
6. **Esc / 일시 중단 / 임무 종료**로 터치를 해제합니다. 임무 도중 카메라 영역을 다시 지정하면 기존 판단을 폐기하고 새 영역으로 계속합니다.

카메라 영역을 지정하지 않으면 시작할 수 없고 전체 화면으로 대체하지 않습니다. 현재·이전 비교 이미지 모두 크롭해서 전달합니다. 화면 세션·크기가 변경되면 다시 보정하고 영역을 지정합니다. 모델은 이륙 상태 UI를 받지 않으며, 사람이 기체를 들고 이동한다고 안내됩니다. 이륙·착륙 버튼은 자동으로 누르지 않습니다.

## 화면과 동작

- 초록 화살표는 전후, 파랑은 좌우, 노랑은 상하, 보라 곡선은 회전입니다. 방향은 기체/카메라 기준입니다. 3D 화면을 드래그하면 시점을 회전하고 휠로 확대합니다. 더블클릭으로 기본 시점을 복원합니다.
- 가상 궤적은 **Android가 수락한 명령**으로만 계산합니다. 실제 기체 위치·속도·거리 측정값이 아닙니다. 기본 이동은 1 가상 단위/초, 회전은 45도/초이며 입력 크기에 비례합니다.
- 수동 버튼과 AI 명령은 같은 실행 이벤트를 사용합니다. 기본 드래그 크기는 100%이며 5–100%로 조절할 수 있습니다. AI는 방향과 시간, 사용자는 드래그 크기를 정합니다.
- 명령당 최대 2초이며 만료 시 터치와 가상 이동이 멈춥니다. 마지막 지시는 다음 판단까지 남습니다. API 판단은 별도 스레드에서 실행되고 3D 렌더링과 Android 갱신을 막지 않습니다.
- **관찰 전용**은 선택 사항입니다. 이 모드에서는 실제 터치나 가상 이동 없이 모델의 제안만 표시합니다.
- 사전 검증 기록, 5분 임무 제한, 화면 픽셀 유사도 검사, Mac 포커스에 따른 AI 중단은 없습니다. 수동 버튼은 놓기·포커스 상실 시 해제합니다.
- 연결 단절, 영상 지연, 좌표계 변경, Android 대상 앱 변경, 잘못된 명령에는 입력을 해제합니다. heartbeat는 이동 시간을 연장하지 않습니다. 늦은 응답과 중복 관찰은 다시 실행하지 않습니다.

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

## 구조

`camera`가 크롭과 영역 저장, `astra`가 Responses 함수 호출, `mission`이 관찰·판단·실행 루프를 담당합니다. `execution`은 AI/수동의 최종 명령과 수락 이벤트를 공유합니다. `simulation`은 렌더러와 분리된 가상 이동 계산이며 `sim_view`와 `qml/`이 Qt Quick 3D 화면을 구성합니다. `android/`와 `guard`는 기존 `jipbul-guard-4` 전송 계약을 보존합니다.

빌드한 scrcpy 서버의 Apache-2.0 라이선스는 `artifacts/android/SCRCPY-LICENSE`에 보존됩니다. 참고: [OpenAI 함수 호출](https://developers.openai.com/api/docs/guides/function-calling), [Qt Quick 3D](https://doc.qt.io/qt-6.11/qml-qtquick3d-view3d.html).
