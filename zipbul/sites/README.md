# 짚불 Sites 배포

사이트: https://zipbul-field-explorer.summits.chatgpt.site

2026-10-09, 소유자 전용으로 최초 배포한 뒤 사용자의 요청으로 로그인 없이 접속할 수 있도록 공개 전환했다. 공개 설정 후 기존 버전을 재배포했으며, 인증 헤더·쿠키 없는 홈과 현장 목록 요청이 리다이렉트 없이 HTTP 200을 반환했다. 현재 버전과 소스 커밋은 `deployment.json`에 기록한다. 모노레포의 제품 안에 `.git`을 추가하지 않도록 Sites 전용 소스 체크아웃은 `/Users/gimdonghyeon/.codex/sites/zipbul-20261009`에 둔다. 원래 로컬 앱의 서버·데이터는 유지한다.

## 동작 범위

- 기존 현장의 원본 GLB, 표시용 GLB, 충돌 GLB, 원본 영상 및 19개 JPEG 근거 프레임을 R2에 보관한다. 영상은 Range 요청으로 재생한다. 전송한 자료는 23개, 총 596,496,006바이트다.
- D1은 현장 JSON, 사용자 연결·검토·보정·경로 기록, 분석 진행 상태를 저장한다. 낡은 revision으로 저장하면 409를 반환한다.
- `gpt-6-astra`를 사용한 새 분석과 근거 대화를 제공한다. 분석은 6개 프레임씩 background Responses로 처리하며 응답 ID를 저장한다. 다음 묶음의 진행과 완료 회수는 화면의 상태 조회로 구동되므로 화면을 닫으면 다시 열었을 때 이어진다.
- 재분석은 사용자 연결과 검토 상태를 별도로 보존한다. 신규 AI 관찰에 임의의 3D 좌표를 만들지 않는다. 위치 미확인 항목은 영상 근거만 열고 자동 공간 이동을 보류한다.
- 새 GLB·영상의 FFmpeg 전처리는 로컬 앱에서 실행한다. Sites에서 새 원본을 직접 가져오는 기능은 아직 제공하지 않으며 화면에서도 이 제한을 알린다. 준비된 다른 현장은 아래 전송 과정으로 추가한다.

## 후속 업데이트

1. 이 폴더의 `api.ts`, `analysis.ts`가 클라우드 API 어댑터다. UI 변경을 의도적으로 반영할 때 제품 폴더에서 `node scripts/site-sync.mjs /Users/gimdonghyeon/.codex/sites/zipbul-20261009`를 실행한다. 이 명령은 최신 로컬 UI를 복사하므로 다른 작업자의 변경을 먼저 확인한다.
2. Sites 스킬의 source helper로 기존 Site의 credential을 받아 빌드·커밋·푸시·패키징한다. 기존 `project_id`를 재사용한다. D1 스키마 변경은 Drizzle 마이그레이션을 생성해서 검토한다.
3. 현재 공개 권한을 유지하여 `save_site_version` 후 `deploy_site_version`으로 배포한다. 키는 Sites 비밀 환경변수만 사용하며 소스·manifest·브라우저에는 넣지 않는다.
4. 새 현장 자료는 `node --import tsx scripts/site-export.ts <scene-id>`로 내보낸다. 로컬 파일 경로가 든 전송 manifest는 Git에서 제외된 `output/sites-transfer.json`에만 둔다.
5. `node scripts/site-upload.mjs output/sites-transfer.json`을 실행하고 숨김 stdin으로 사이트 URL, 자료 전송 비밀값, Sites 서비스 접근 토큰을 전달한다. 값은 인자·파일·로그에 남기지 않는다. 원본 파일은 8MiB 조각으로 업로드하며 동일 해시의 자료는 재사용한다. 기존 현장의 다른 내용으로 된 파일 및 검토 기록은 덮어쓰지 않는다.

## 검증

2026-10-09 실제 배포 검증 완료: 비로그인 접근은 401, 자산 23개의 크기 일치, 영상 Range 및 277.89초 재생, 3D 로딩, 17개 관계 노드, 접지 상태에서 약 0.60m 워크스루 이동을 확인했다. 브라우저 오류는 없었다. 검토 상태를 변경·조회한 뒤 원래 상태로 복구했고, Astra 근거 대화와 1개 프레임 새 분석이 완료됐다(새 위험 후보 0개). 이는 표본 기능 확인이며 전체 영상의 위험 탐지 성능이나 현장 안전 판정이 아니다. Sites 소스와 빌드 파일 207개에서 실제 API 키가 포함되지 않았음도 확인했다.

- `node --import tsx --test sites/api.test.ts`: revision 충돌·수동 기록 보존·경로 무효화·Range·background 분석 응답 보존을 검사한다. OpenAI 응답은 모의 응답이다.
- Sites 체크아웃에서 `npm run typecheck` 및 Sites build helper가 통과했다.
- `scripts/site-verify.mjs`는 실제 배포 URL에서 자료 크기·Range·비공개 접근, 브라우저 3D·영상·그래프·이동, 검토 저장/원상 복구, 실제 Astra 대화와 1개 프레임 재분석을 확인한다. 결과는 `output/sites-verification.json`, 화면은 `output/sites-*.png`에 저장한다. 실제 분석은 비용이 발생하고 새 분석 기록을 남긴다.

API 키는 사용자의 명시적 재사용 허가 후 Sites의 `OPENAI_API_KEY` secret으로 저장했다. 자료 전송 전용 키는 `ZIPBUL_UPLOAD_TOKEN` secret이다. 공개 전환 후에도 전송 API의 토큰 검증은 유지된다.
