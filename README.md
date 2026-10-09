# 짚불 (Zipbul)

현장 공간과 원본 영상의 근거를 연결하는 산업안전 탐사 도구입니다. iPhone LiDAR로 수집한 공간을 3D로 탐사하고, OpenAI GPT-6 Astra의 위험 후보와 사람이 확인한 위치·검토 기록을 함께 살펴봅니다.

**시연 사이트:** [Sites 공개 배포](https://zipbul-field-explorer.summits.chatgpt.site) · [Mac 터널 배포](https://zipbul.summit1123.co.kr)

## 제품 구성

| 폴더 | 역할 | 실행·검증 안내 |
| --- | --- | --- |
| `zipscan/` | iOS LiDAR 수집, 원본 영상·카메라·깊이·메시 내보내기 | [스캐너 README](zipscan/README.md) |
| `zipscan/Texture/` | 수집한 원본으로 사진 텍스처가 내장된 GLB 생성 | [텍스처 README](zipscan/Texture/README.md) |
| `zipbul/` | 3D 분석·워크스루, 영상 근거, 수동 위치 연결, 관계도, AI 분석 | [메인 앱 README](zipbul/README.md) |
| `zipcontrol/` | Android 카메라와 Astra 이동 지시를 연결한 Mac 시연 앱 | [컨트롤러 README](zipcontrol/README.md) |

수집 세션을 Texture에서 처리한 **GLB + 원본 영상**을 메인 앱으로 가져옵니다. 카메라 메타데이터가 없어도 수동 위치 연결을 사용할 수 있습니다. 세 제품은 이 저장소 하나에서 관리합니다.

## 메인 앱 실행

Node.js 22 이상, `ffmpeg`, `ffprobe`가 필요합니다. AI 기능은 저장소 루트의 `.env`에 개발자가 별도로 설정한 `OPENAI_API_KEY`를 사용합니다. 키는 서버에서만 읽습니다.

```sh
git clone https://github.com/kshkdh18/zipbul-project.git
cd zipbul-project/zipbul
npm ci
npm run dev
```

http://127.0.0.1:3000 에서 **현장 추가**로 GLB와 MP4/MOV를 가져옵니다. 촬영 데이터, 준비된 현장, API 키, 빌드 결과물은 Git에 포함하지 않습니다. 새로 받은 저장소에서는 입력 자료를 별도로 준비해야 합니다.

배포된 시연 사이트는 이 Mac의 프로덕션 서버를 터널로 연결하므로 Mac의 전원·네트워크가 유지되어야 합니다. 배포 구성은 [메인 앱 배포 안내](zipbul/README.md#mac-터널-배포), 별도 Sites 배포는 [Sites 안내](zipbul/sites/README.md)를 참고하세요.

## 검증

```sh
# 메인 앱: 로컬 저장·데이터 계약 및 모의 클라우드 API 테스트
cd zipbul
npm test
npm run typecheck
npm run build

# 컨트롤러: 기기 제어 없이 자동 테스트
cd ../zipcontrol
uv run --frozen pytest -q
uv run --frozen ruff check src tests tools android/build.py

# 텍스처 처리
cd ../zipscan/Texture
uv run --frozen pytest -q

# 스캐너 Core: 호환되는 Apple 개발 도구 필요
cd ..
swift test
```

메인 앱의 `npm run test:browser`는 실행 중인 로컬 서버와 README에 기록한 현장 자료, Playwright Chromium을 사용합니다. 테스트용 복제 현장으로 수동 연결·검토 보존, 3D/2D 관계도, 이동·충돌, 파일 업로드를 확인합니다. 세부 결과와 검증하지 못한 항목은 [최종 제출 검증 기록](docs/FINAL_VALIDATION.md)에 정리합니다.

AI의 관찰 후보는 현장 확인을 돕는 정보입니다. 재구성 장면과 보정된 이동 안내는 추정·시뮬레이션이며 실제 현장의 안전성이나 통행 가능성을 보장하지 않습니다. 개발은 Codex, AI 모델과 서비스는 OpenAI만 사용합니다.
