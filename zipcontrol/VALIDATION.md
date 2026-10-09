# 검증 기록 · 2026-10-09

## 자동 검사

- 기존 전송·좌표·보정·멀티터치·임무 테스트를 이관하고 변경된 동작에 맞게 갱신했다.
- 크롭 이미지의 실제 API 요청을 디코딩해 현재·이전 이미지 모두 선택 영역 밖의 픽셀을 포함하지 않는지 검사한다. 영역 누락·범위 오류·영역 변경 중 늦은 응답 폐기도 포함한다.
- 공통 명령 이벤트, 수동/AI 입력, 8방향·복합 이동·회전 후 전진, 만료·중단·거부·연결 오류의 가상 이동 중지를 검사한다.
- 검증 기록 없이 입력 준비, 5분 초과 실행, Mac 포커스 상실 시 AI 유지와 수동 해제, 화면 유사도 검사 제거를 검사한다.
- 최종 실행 결과: **143개 테스트 통과**, Ruff 통과, sdist/wheel 빌드 통과. wheel에 QML 두 파일과 진단 HTML이 포함되는 것을 확인했다.

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

실제 DJI 카메라를 연결하고 사람이 기체를 들고 이동하면서 Astra의 다음 지시를 받는 전체 시연, 통제된 물리 USB 분리 시 해제 시간 측정은 **미확인**이다. 위 실기 검사는 Chrome 진단 화면의 터치·영상·3D 연동을 확인한 것이며 기체 이동이나 비행 결과를 측정하지 않았다. 이 미확인 상태가 앱 실행을 잠그지는 않는다.
