# Zipscan package 1.0

ZIP 최상위에 아래 파일을 둡니다. 파일명은 한국시간의 **세션 시작 시각**을 사용한 `yyyyMMdd-HHmmss_<UUID>.zip`입니다. UUID가 세션 식별자이며 파일명에 의존해 데이터를 연결하지 않습니다.

| 파일 | 내용 |
|---|---|
| `manifest.json` | `format_version`, `session_id`, UTC ISO 8601 시작·종료 시각, 기기·OS·앱 버전, 실제 설정, 시간·좌표 규약, 상태·요약·누락, 파일 크기·SHA-256 |
| `video.mp4` | H.264, 음성 없음, 센서 방향·크기의 카메라 영상. UI·메쉬 합성, 픽셀 회전·크롭 없음 |
| `frames.jsonl` | 프레임 ID, AR 시각, 영상 기록 상태·PTS, 카메라 자세·내부 파라미터·영상 크기, 추적 상태, 표시 변환과 표시 영역 크기 |
| `mesh.obj` | 최종 앵커 메쉬의 세션 좌표 꼭짓점·삼각형. 미터, 텍스처 없음 |
| `depth.bin` | 행 패딩 없는 Float32 little-endian 깊이 |
| `confidence.bin` | 행 패딩 없는 UInt8 신뢰도 |
| `depth-index.jsonl` | 대응 프레임 ID·AR 시각, 크기, 바이너리 오프셋·길이, 깊이 내부 파라미터 또는 누락 사유 |
| `events.jsonl` | 초기화·추적 변화·누락·발열·저장 오류·종료 사유 |
| `validation.json` | 검사 시각, 검증 문제·경고, 영상·깊이·메쉬 집계 |

JSON 키는 snake_case입니다. 선택 값이 없으면 해당 키를 생략합니다. JSONL은 각 행 끝에 LF가 있어야 합니다. `manifest.json`의 체크섬 목록은 자신을 제외한 모든 최상위 일반 파일을 포함합니다. 검증 보고서도 포함합니다. ZIP에는 원본 폴더를 감싸는 추가 디렉터리가 없습니다.

## 프레임과 시간

- `frame_id`는 수집 준비 이후의 AR 콜백 번호입니다. 영상 또는 깊이 저장 대상으로 선택한 프레임을 `frames.jsonl`에 남깁니다. 의도적으로 샘플링하지 않은 AR 프레임의 ID는 건너뜁니다.
- 같은 ARFrame의 카메라·깊이만 연결합니다. `ar_timestamp`는 ARKit의 단조 증가 시간(초), `time_origin`은 첫 수집 프레임의 AR 시각입니다. UTC 시각과 혼동하지 마세요.
- 저장 영상의 `video_pts = ar_timestamp - time_origin`이며 1/1,000,000초 정밀도로 반올림합니다. MP4 영상 트랙에도 동일한 time scale을 설정합니다.
- `video_status`는 `written`, `not_sampled`, `queue_full`, `encoder_busy`, `encode_failed` 중 하나입니다. `written`일 때만 `video_pts`가 있습니다. 파일 내 실제 샘플과 PTS로 연결하며, AR frame_id를 영상 프레임 번호로 취급하지 않습니다.
- 깊이의 시각은 연결된 ARFrame의 시각입니다. 별도의 LiDAR 하드웨어 시각을 얻었다고 주장하지 않습니다. 저장 값은 `sceneDepth`이며 `smoothedSceneDepth`가 아닙니다.
- 영상 읽기 중 AVAssetReader가 반환하는 **0 sample 경계 버퍼**는 프레임 수에 포함하지 않습니다.

## 좌표와 깊이 투영

- 메쉬·카메라 변환은 동일 세션의 ARKit 오른손 좌표계, 미터 단위이며 +Y가 위입니다. 카메라는 -Z 방향을 봅니다. GPS나 다른 세션의 좌표와 연결되지 않습니다.
- `camera_transform`은 **camera-to-world 4×4**, `intrinsics`는 **3×3 K**입니다. Swift SIMD의 열 저장 방식을 그대로 덤프하지 않고 **행 단위 중첩 배열**로 저장합니다.
- 이미지 원점은 좌상단 픽셀 중심 (0,0), +u는 오른쪽, +v는 아래입니다. 깊이는 카메라 평면에서 광학 축을 따라 잰 미터 값입니다.
- 원본 RGB는 센서 방향으로 저장합니다. `settings.video_transform`은 MP4 재생 변환 `[a,b,c,d,tx,ty]`이며 현재 identity입니다.
- 각 프레임의 `display_transform`은 정규화된 원본 영상 좌표에서 AR 미리보기 좌표로 가는 ARKit affine transform입니다. `display_viewport`는 그 변환에 사용한 `[width,height]` 논리 포인트입니다. 화면 aspect-fill 크롭을 원본 영상이나 깊이에 적용하지 마세요.
- 깊이 해상도가 `(Wd,Hd)`, 원본 영상이 `(Wi,Hi)`이면 `Kd = diag(Wd/Wi, Hd/Hi, 1) × K`입니다. 각 저장 깊이 인덱스에 Kd를 함께 기록합니다.
- 깊이 픽셀 `(u,v)`, 값 `d`의 카메라 좌표는 `[(u-cx)/fx*d, -(v-cy)/fy*d, -d, 1]`이며 camera-to-world를 곱해 세션 좌표를 얻습니다.
- NaN·무한대·0 이하 깊이는 유효한 표면점으로 사용하지 않습니다. 원본 값 자체는 바이너리에 보존합니다. 신뢰도 값은 0 low, 1 medium, 2 high입니다.

앵커별 최신 CPU 메쉬를 유지하고, 제거된 앵커를 제외합니다. OBJ는 각 앵커의 변환을 이미 적용한 세계 좌표입니다. 앵커 변환을 다시 곱하지 마세요. 메쉬 이력·ARWorldMap·추적 후 과거 자세 보정은 제공하지 않으므로 장시간 이동에 따른 공간 오차는 별도 검증 대상입니다.

## 저장, 상태, 복구

원본은 `Documents/Sessions/<UUID>/`, ZIP은 `Documents/Exports/`입니다.

- 기록 프레임의 큰 버퍼는 최대 4개, 쓰기 대기 메타데이터는 최대 128개입니다. 큰 버퍼가 가득 차면 영상·깊이 누락을 해당 프레임에 기록합니다. 메타데이터까지 가득 차면 수집을 종료하며 저장하지 못한 개수는 manifest와 종료 이벤트에 남깁니다.
- 영상·깊이는 스트리밍으로 쓰고 JSONL과 바이너리를 주기적으로 동기화합니다. 파일 시스템 장애에 대한 무손실 보장은 아닙니다.
- `recording` → `finalizing` → `complete`/`partial`/`failed`. 정상 종료, 필수 산출물 검증 통과, 예상하지 않은 샘플 누락 없음일 때만 `complete`입니다. 추적 불안정은 별도 경고입니다.
- 사용자 종료와 시간 상한은 정상 종료입니다. 백그라운드, AR 중단·실패, 공간 부족, 치명적 발열은 조기 종료로 표시합니다. `serious` 발열은 경고, `critical`은 종료합니다.
- 앱 재실행 시 `recording`/`finalizing` 세션을 검증하고 부분 결과로 복구합니다. 성공적으로 읽힌 자료가 하나도 없으면 `failed`입니다. 강제 종료된 MP4와 저장 전 최종 메쉬는 복구를 보장하지 않습니다.
- 복구 시 보이는 길이는 읽힌 프레임에서 얻은 길이이며, 강제 종료 시점까지 모두 저장되었다는 뜻이 아닙니다.
- 내보내기 전 원본 크기·SHA-256을 검사합니다. 임시 ZIP을 스트리밍 생성하고 각 entry의 CRC와 SHA-256까지 검증한 후 최종 파일로 교체합니다. 실패하면 원본과 기존 정상 ZIP을 유지합니다.

## 참고

- [ARKit sceneDepth](https://developer.apple.com/documentation/arkit/arframe/scenedepth)
- [ARKit reconstructed scene](https://developer.apple.com/documentation/arkit/visualizing-and-interacting-with-a-reconstructed-scene)
- [ZIPFoundation 0.9.20](https://github.com/weichsel/ZIPFoundation/releases/tag/0.9.20)
