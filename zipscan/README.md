# Zipscan v0.1

LiDAR iPhone으로 실내의 메쉬·카메라 영상·깊이·신뢰도·카메라 자세를 함께 수집하는 네이티브 앱입니다. iOS 17 이상, iPhone 전용이며 촬영 방향은 `landscapeRight`, 기본 상한은 600초입니다. 앱 화면·권한 설명·진단 메시지는 영어로 표시합니다.

## 사용

1. **New scan → Start scan**을 누르고 카메라 접근을 허용합니다. 최소 6GB가 필요합니다.
2. 가로로 들고 벽·바닥·물체를 천천히 비춥니다. 추적과 깊이가 준비되면 녹화 시간이 시작됩니다. 준비가 30초 안에 끝나지 않으면 종료합니다.
3. **Stop and save**을 누르거나 10분 자동 종료를 기다립니다. 저장·검증이 끝날 때까지 앱을 열어 둡니다.
4. 결과의 **3D model / Video / Quality**을 확인합니다. 3D는 회전·확대와 시점 초기화를 지원합니다.
5. **Export ZIP**로 파일 앱이나 공유 시트를 사용합니다. Finder의 iPhone → 파일 → Zipscan에서도 원본과 ZIP을 가져갈 수 있습니다.
6. 목록의 휴지통은 확인 후 해당 세션 원본과 내보낸 ZIP을 함께 삭제합니다. 이미 외부로 공유한 파일은 삭제하지 않습니다.

ZIP 이름은 **`yyyyMMdd-HHmmss_<session_id>.zip`**입니다. 시간은 **촬영 세션 시작 시각, 한국시간(Asia/Seoul)**이며 다시 내보내도 이름이 같습니다.

메쉬 색은 공간 형태를 보여줄 뿐 위험도·안전 판정이 아닙니다. 수집 앱에는 분석, 원격 전송, 음성, 일시정지·재개·세션 병합을 포함하지 않습니다.

**Mac 텍스처 후처리**는 [Texture/README.md](Texture/README.md)를 참고하세요. 기존 ZIP의 원본 영상·카메라·깊이로 텍스처 GLB와 OBJ를 만들며, iPhone의 수집 부하는 늘리지 않습니다.

## 빌드

```sh
cd /Users/ksh/zipbulProject/zipscan
xcodegen generate
open Zipscan.xcodeproj
```

Xcode에서 `Zipscan` scheme과 연결된 iPhone을 선택해 실행합니다. `project.yml`과 생성한 프로젝트를 함께 관리합니다. 다른 개발자의 Mac에서는 `DEVELOPMENT_TEAM`을 해당 계정으로 바꿉니다. ZIPFoundation은 SwiftPM에서 **0.9.20 exact**로 고정합니다.

```sh
xcrun devicectl list devices
# Xcode destination에는 실제 기기의 UDID를 사용합니다.
xcodebuild -project Zipscan.xcodeproj -scheme Zipscan \
  -destination 'id=<iPhone UDID>' -derivedDataPath DerivedData \
  -allowProvisioningUpdates build
```

## 코드 구성

- `App/`: SwiftUI 화면, ARKit/RealityKit 실시간 미리보기, AVAssetWriter 수집, 세션 관리. 결과의 OBJ 탐색은 SceneKit을 사용합니다.
- `Core/`: 패키지 모델, 샘플링, 좌표·바이너리 처리, OBJ, 검증, 복구, 스트리밍 ZIP. macOS에서도 시험할 수 있는 로컬 Swift Package입니다.
- `Tools/ZipscanValidate/`: Mac에서 내보낸 세션을 독립 검증하는 CLI.
- `Tests/`, `AppTests/`, `UITests/`: 데이터 계약, 실제 Recorder 파이프라인, UI 시험.

자세한 계약은 [package-v1.md](docs/package-v1.md), 확인한 결과와 남은 시험은 [verification.md](docs/verification.md)를 참고하세요.

## 검증 실행

```sh
swift test
swift run zipscan-validate /path/to/unzipped-session

xcodebuild -project Zipscan.xcodeproj -scheme Zipscan \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath DerivedDataSimulator -only-testing:ZipscanTests test

xcodebuild -project Zipscan.xcodeproj -scheme Zipscan \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath DerivedDataSimulator \
  -only-testing:ZipscanUITests/ZipscanUITests/testLibraryAndUnsupportedDevice test
```

결과·삭제 UI 시험에는 정상 ZIP을 시뮬레이터 전용 fixture로 준비합니다. 이 도구는 원본 ZIP을 수정하지 않습니다. 실제 기기나 다른 세션은 삭제하지 않습니다.

```sh
uv run --script Tools/prepare_ui_fixture.py /path/to/session.zip --simulator '<simulator UUID>'
xcodebuild -project Zipscan.xcodeproj -scheme Zipscan \
  -destination 'platform=iOS Simulator,id=<simulator UUID>' \
  -derivedDataPath DerivedDataSimulator \
  -only-testing:ZipscanUITests/ZipscanUITests/testImportedFixtureResultsAndDeletion test
```

실기기 전용 `testPhysicalDeviceSmoke`는 실제 후면 카메라로 15초 촬영하고 자동으로 ZIP을 만듭니다. 기기를 들고 준비한 뒤 명시적으로 실행하세요. **시뮬레이터는 LiDAR 수집을 검증하지 못합니다.**

Debug 빌드에만 `--smoke-seconds 15 --auto-export`, `--depth-5hz`, `--video-15fps` 진단 인수가 있습니다. 기본 설정은 30fps/10Hz이며 이 인수들은 Release에서 무시됩니다. 기본 설정이 10분 시험에 실패하면 다음 시험에서 30fps/5Hz, 이후 15fps/5Hz를 시도합니다. 세션 중 자동으로 설정을 바꾸지 않습니다.
