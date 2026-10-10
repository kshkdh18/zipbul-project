import XCTest

final class ZipscanUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    func testLibraryAndUnsupportedDevice() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(ko)", "-AppleLocale", "ko_KR"]
        app.launch()
        XCTAssertTrue(app.buttons["new-scan"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.buttons["new-scan"].label, "New scan")
        app.buttons["new-scan"].tap()
        XCTAssertTrue(app.staticTexts["Ready to scan"].waitForExistence(timeout: 5))
        #if targetEnvironment(simulator)
        XCTAssertFalse(app.buttons["start-scan"].isEnabled)
        #endif
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); screenshot.lifetime = .keepAlways; add(screenshot)
        app.buttons["Back"].tap()
        XCTAssertTrue(app.buttons["new-scan"].exists)
    }
    func testImportedFixtureResultsAndDeletion() throws {
        #if targetEnvironment(simulator)
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(ko)", "-AppleLocale", "ko_KR"]
        app.launch()
        let fixture = "00000000-0000-4000-8000-000000000001"
        let row = app.buttons["session-" + fixture]
        guard row.waitForExistence(timeout: 10) else { throw XCTSkip("The simulator fixture is not installed.") }
        row.tap()
        XCTAssertTrue(app.buttons["Reset view"].waitForExistence(timeout: 15))
        let mesh = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); mesh.lifetime = .keepAlways; add(mesh)
        app.buttons["Reset view"].tap()
        app.segmentedControls.buttons["Video"].tap()
        XCTAssertTrue(app.otherElements["recorded-video"].waitForExistence(timeout: 5))
        app.segmentedControls.buttons["Quality"].tap()
        XCTAssertTrue(app.staticTexts["Required data and video–depth alignment passed validation."].exists)
        XCTAssertTrue(app.staticTexts["Tracking was unstable during part of the scan."].exists)
        app.buttons["export-zip"].tap()
        XCTAssertTrue(app.staticTexts["export-complete"].waitForExistence(timeout: 30))
        app.terminate(); app.launch()
        XCTAssertTrue(app.buttons["delete-session-" + fixture].waitForExistence(timeout: 10))
        app.buttons["delete-session-" + fixture].tap()
        app.alerts.buttons["Cancel"].tap()
        XCTAssertTrue(row.exists)
        app.buttons["delete-session-" + fixture].tap()
        app.alerts.buttons["Delete"].tap()
        XCTAssertTrue(row.waitForNonExistence(timeout: 10))
        #else
        throw XCTSkip("Simulator-only test; does not delete real user scans")
        #endif
    }

    // Run explicitly on a LiDAR iPhone. This records the scene visible to its rear camera.
    func testPhysicalDeviceSmoke() throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("Requires a physical LiDAR device")
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
        XCTAssertTrue(app.staticTexts["session-status-complete"].exists, "Check the reasons for partial saving")
        #endif
    }
}
