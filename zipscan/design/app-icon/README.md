# Zipscan 앱 아이콘

청록색 입체 공간 윤곽과 주황색 Z 모양 스캔 궤적을 결합했다. 앱의 기존 남색·청록색·주황색 색상을 따랐다.

- 에셋: `../../App/Assets.xcassets/AppIcon.appiconset/AppIcon.png`
- 규격: 1024 × 1024 PNG, 불투명 배경, 모서리 마스크 없음
- 생성: 내장 imagegen 도구. 생성 프롬프트는 `prompt.txt`에 보관했다.
- Xcode: `App/Assets.xcassets`를 앱의 Resources에 포함하고 `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon`을 사용한다.
- 현재 XcodeGen 설정의 `sources: [App]`와 AppIcon 빌드 설정을 그대로 사용한다. 메인 개발 작업에서 `xcodegen generate`를 실행하면 새 에셋 카탈로그가 프로젝트에 포함된다.

이 작업은 아이콘 에셋과 이 폴더만 추가했다. 앱 소스와 생성된 Xcode 프로젝트는 수정하지 않았다.
