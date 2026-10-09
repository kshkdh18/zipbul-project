# Zipscan Texture — Mac 텍스처 후처리

기존 Zipscan ZIP의 최종 메쉬, 원본 카메라 영상, 카메라 자세·내부 파라미터, 같은 프레임의 깊이·신뢰도로 사진 텍스처를 만듭니다. **생성형 이미지, 빈 공간 채우기, 메쉬 변형·간소화는 사용하지 않습니다.**

## 실행

Python 환경은 `uv`로 관리하며 시스템 FFmpeg 설치는 필수가 아닙니다. 영상은 PyAV로 실제 PTS를 읽어 디코딩합니다. 초기 의존성 설치 이후 처리와 결과 뷰어는 로컬에서 실행됩니다.

```sh
cd /Users/ksh/zipbulProject/zipscan/Texture
uv sync --locked

uv run zipscan-texture bake \
  ../Tests/20261009-115704_105bfbad-4a6f-4174-98ea-c10341cda210.zip \
  --output ../artifacts/textured-105bfbad-4a6f-4174-98ea-c10341cda210 \
  --profile quality

uv run zipscan-texture view \
  ../artifacts/textured-105bfbad-4a6f-4174-98ea-c10341cda210 \
  --port 8767
```

브라우저에서 표시되는 `http://127.0.0.1:8767/viewer.html`을 엽니다. 서버는 localhost에만 바인딩합니다. 다른 포트가 필요하면 `--port`를 바꿉니다. 뷰어는 Three.js 0.186.1을 포함하므로 CDN 연결이나 영상 업로드가 없습니다.

- **사진 텍스처 / 원본 형태**: 같은 메쉬에서 표시 방식을 비교합니다.
- **촬영 위치로 이동**: 저장된 카메라 위치로 이동합니다.
- **천장 숨기기 / 높이 조절**: 표시만 잘라 내부를 확인합니다. 출력 메쉬는 변경하지 않습니다.
- 드래그 회전, 휠 확대, 우클릭 이동, 더블클릭한 표면으로 가까이 이동합니다.
- 좁은 화면에서는 **정보** 버튼으로 패널을 여닫습니다.

## 출력

| 파일 | 용도 |
|---|---|
| `textured.glb` | 텍스처가 내장된 단일 3D 파일. glTF 2.0, 미터, 원본 ARKit 좌표 유지 |
| `textured.obj`, `textured.mtl`, `textures/` | OBJ/MTL 호환 도구용. 함께 이동해야 함 |
| `source-frames.json` | 사용 후보 프레임의 원본 frame_id, PTS, 카메라 행렬·K, 선명도, 색 보정 계수 |
| `face-sources.npz` | 원본 삼각형별 source_frame_id. -1은 대응 없음. export_face_order는 GLB primitive/OBJ 면 순서 → 원본 면 번호. face_patch는 내부 디버그용 패치 ID |
| `report.json` | 입력 해시·상태, 적용 면적, 원본/출력 면 수, 설정, 결과 파일 해시, 한계 |
| `viewer.html`, `viewer.js`, `vendor/` | 로컬 3D 비교 뷰어 |
| `.work/` | 압축 해제·키프레임·시점 선택·색 보정 캐시. 결과 생성 후 삭제해도 GLB/OBJ/뷰어 사용 가능 |

`report.json.files`의 체크섬은 모델·매핑·텍스처 산출물을 대상으로 합니다. HTML과 캡처 이미지는 포함하지 않습니다. 원본 ZIP과 capture manifest는 수정하지 않습니다. 파생 결과의 session_id로 원본 세션에 연결합니다.

## 품질 설정과 처리

기본 `quality`는 **0.75초 구간당 사진 1장, 최대 1920px, 메쉬 전체 유지**입니다. 각 구간의 움직임이 작은 두 프레임을 디코딩하고 선명도로 최종 선택합니다. `compact`는 1.5초/1024px이며 메쉬 간소화는 하지 않습니다.

`--interval`, `--image-size`, `--atlas-size`, `--max-distance`, `--depth-tolerance`, `--min-confidence`로 실험 설정을 명시할 수 있습니다. 실제 설정은 보고서에 남습니다.

1. ZIP 경로·중복 파일·크기·SHA-256, 행렬과 깊이 인덱스 연결을 검사합니다. `partial`도 필수 데이터가 정상이면 읽습니다.
2. 영상의 실제 PTS와 `video_pts`를 맞춥니다. 카메라 frame_id를 영상 인덱스로 가정하지 않습니다. 추적 정상, 영상 저장 성공, 동일 ARFrame 깊이·신뢰도가 있는 프레임만 사용합니다.
3. 원본 메쉬를 카메라 좌표로 투영합니다. 삼각형 중심·세 꼭짓점·세 변의 중점에서 깊이 일치를 검사합니다. 기본 허용차는 `0.12m + 0.02 × 광학축 깊이`, 범위 0.2–5m, confidence 1 이상입니다.
4. 정면 정도·거리·화면 중심과의 거리·선명도·깊이 오차로 시점을 선택합니다. 두 번째 후보도 유지하여 연결된 면의 불필요한 사진 전환을 줄입니다.
5. 겹쳐 관측한 표면의 색으로 제한적인 선형 RGB 노출 보정을 합니다(0.75–1.33 배). 거의 같은 방향의 인접 면 경계는 양쪽에서 깊이가 맞는 경우만 2px 폭, 채널당 최대 16/255 이내로 보정합니다.
6. 실제 사용 영역을 약 256px 단위 패치로 나누어 UV atlas에 배치하고, 8px 복제 여백을 둡니다. JPEG quality 95, 색차 다운샘플링 없음입니다. GLB의 사진 재질은 `KHR_materials_unlit`로 조명에 의해 다시 어두워지지 않습니다.

카메라 원본 픽셀 좌표만 사용하며 **화면의 display_transform이나 aspect-fill 크롭을 적용하지 않습니다.** ARKit camera-to-world는 행 단위 행렬, 카메라는 -Z 전방/+Y 위, 이미지의 +v는 아래입니다. glTF의 v는 위쪽 원점, OBJ의 v는 아래쪽 원점으로 각각 기록합니다. 원본 영상에 별도 회전 행렬이 적용된 패키지는 추측해서 처리하지 않고 거부합니다.

양면 렌더링은 탐색을 위한 표시이며, 반대쪽 면을 별도로 촬영했다는 의미는 아닙니다. 결과의 적용 면적은 설정된 기하·깊이 조건을 통과한 면의 비율이며 실제 정확도의 인증 점수가 아닙니다.

## 검증

```sh
uv run pytest -q
```

시험은 축·회전·이동 변환, 광학축 깊이와 가림, 신뢰도, atlas 여백/UV 상하 방향, 색 경계 보정, 실제 MP4의 프레임 누락, ZIP 경로/체크섬 오류, 원본 보존과 GLB 내보내기를 포함합니다.

[실제 행사장 결과](../docs/texture-verification.md)를 확인하세요. 원본의 구멍, 움직이는 물체, 과거 카메라 자세와 최종 메쉬 사이의 누적 오차는 이 버전에서 복구하지 않습니다. 사진 전환 경계도 완전히 제거되지는 않습니다.

## 구현 위치와 의존성

- `session.py`, `keyframes.py`: 입력 무결성·시간 대응·사진 선택.
- `geometry.py`, `selection.py`: 투영·깊이 가림·관측 시점·색 보정.
- `atlas.py`, `export.py`: 경계 보정·atlas·UV·GLB/OBJ와 대응표.
- `pipeline.py`, `cli.py`, `static/`: 실행·보고서·localhost 뷰어.

NumPy/SciPy/PyAV/OpenCV/Pillow 버전은 `uv.lock`으로 고정합니다. Three.js 원본과 MIT 라이선스는 `static/vendor/`에 포함했습니다. 원리 참고: [Apple camera intrinsics](https://developer.apple.com/documentation/arkit/arcamera/intrinsics), [PyAV video frames](https://pyav.org/docs/stable/api/video.html), [glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).
