import XCTest

final class ZipscanUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    func testLibraryAndUnsupportedDevice() {
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.buttons["new-scan"].waitForExistence(timeout: 10))
        app.buttons["new-scan"].tap()
        XCTAssertTrue(app.staticTexts["촬영 준비"].waitForExistence(timeout: 5))
        #if targetEnvironment(simulator)
        XCTAssertFalse(app.buttons["start-scan"].isEnabled)
        #endif
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); screenshot.lifetime = .keepAlways; add(screenshot)
        app.buttons["돌아가기"].tap()
        XCTAssertTrue(app.buttons["new-scan"].exists)
    }
    func testImportedFixtureResultsAndDeletion() throws {
        #if targetEnvironment(simulator)
        let app = XCUIApplication(); app.launch()
        let fixture = "00000000-0000-4000-8000-000000000001"
        let row = app.buttons["session-" + fixture]
        guard row.waitForExistence(timeout: 10) else { throw XCTSkip("시뮬레이터 전용 fixture가 설치되지 않았습니다.") }
        row.tap()
        XCTAssertTrue(app.buttons["시점 초기화"].waitForExistence(timeout: 15))
        let mesh = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); mesh.lifetime = .keepAlways; add(mesh)
        app.buttons["시점 초기화"].tap()
        app.segmentedControls.buttons["영상"].tap()
        XCTAssertTrue(app.otherElements["recorded-video"].waitForExistence(timeout: 5))
        app.segmentedControls.buttons["수집 품질"].tap()
        XCTAssertTrue(app.staticTexts["필수 데이터와 영상·깊이 연결 검증을 통과했습니다."].exists)
        app.buttons["export-zip"].tap()
        XCTAssertTrue(app.staticTexts["export-complete"].waitForExistence(timeout: 30))
        app.terminate(); app.launch()
        XCTAssertTrue(app.buttons["delete-session-" + fixture].waitForExistence(timeout: 10))
        app.buttons["delete-session-" + fixture].tap()
        app.alerts.buttons["취소"].tap()
        XCTAssertTrue(row.exists)
        app.buttons["delete-session-" + fixture].tap()
        app.alerts.buttons["삭제"].tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 10))
        #else
        throw XCTSkip("실제 사용자 세션을 삭제하지 않는 시뮬레이터 전용 시험")
        #endif
    }

    // Run explicitly on a LiDAR iPhone. This records the scene visible to its rear camera.
    func testPhysicalDeviceSmoke() throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("LiDAR 실기기 전용")
        #else
        let app = XCUIApplication()
        app.launchArguments = ["--smoke-seconds", "15", "--auto-export"]
        addUIInterruptionMonitor(withDescription: "Camera permission") { alert in
            let buttons = alert.buttons
            if buttons["허용"].exists { buttons["허용"].tap(); return true }
            if buttons["Allow"].exists { buttons["Allow"].tap(); return true }
            if buttons["OK"].exists { buttons["OK"].tap(); return true }
            if buttons["확인"].exists { buttons["확인"].tap(); return true }
            return false
        }
        app.launch()
        app.tap()
        XCTAssertTrue(app.buttons["export-zip"].waitForExistence(timeout: 90))
        XCTAssertTrue(app.staticTexts["export-complete"].waitForExistence(timeout: 90))
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); screenshot.lifetime = .keepAlways; add(screenshot)
        XCTAssertTrue(app.staticTexts["session-status-complete"].exists, "부분 저장 사유를 검사하세요")
        #endif
    }
}
