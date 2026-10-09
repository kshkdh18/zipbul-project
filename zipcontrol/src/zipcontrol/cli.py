import argparse
import json
import signal
import time
from pathlib import Path

from .bridge import Bridge


def main():
    parser = argparse.ArgumentParser(description="Zipcontrol: Android touch and handheld camera guidance")
    parser.add_argument(
        "command",
        nargs="?",
        default="gui",
        choices=[
            "gui",
            "capture",
            "validate",
            "validate-guard",
            "benchmark-astra",
            "benchmark-luna",
            "validate-usb",
        ],
    )
    parser.add_argument("--serial")
    parser.add_argument("--server-path")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument(
        "--image", type=Path, help="benchmark-luna: explicitly supplied already-cropped camera image"
    )
    parser.add_argument("--samples", type=int, default=20, help="benchmark-luna calls per model")
    parser.add_argument("--goal", default="빨간 상자가 화면 중앙에 오도록 시점을 맞춰")
    args = parser.parse_args()

    if args.command == "benchmark-luna":
        from .benchmark import benchmark_luna

        result = benchmark_luna(
            args.serial, args.server_path, args.output, image=args.image, samples=args.samples, goal=args.goal
        )
        if result["status"] != "passed":
            raise SystemExit(1)
        return

    if args.command in ("validate-guard", "benchmark-astra", "validate-usb"):
        from .guard_validation import benchmark_astra, validate_guard, validate_usb

        fn = {
            "validate-guard": validate_guard,
            "benchmark-astra": benchmark_astra,
            "validate-usb": validate_usb,
        }[args.command]
        result = fn(args.serial, args.server_path, args.output)
        if result.get("status") != "passed":
            raise SystemExit(1)
        return

    if args.command == "gui":
        from .gui import run

        return run(args.serial, args.server_path)

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    if args.command == "validate":
        from .validation import run_validation

        run_validation(args.serial, args.server_path, args.output)
        return
    from PIL import Image

    output = args.output or Path("artifacts/capture.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    with Bridge(args.serial, args.server_path) as bridge:
        time.sleep(args.seconds)
        frame = bridge.latest_frame()
        Image.fromarray(frame.rgb).save(output)
        print(
            json.dumps(
                {
                    "device": bridge.transport.device_name,
                    "size": [frame.width, frame.height],
                    "fps": bridge.fps,
                    "frames": frame.sequence,
                    "output": str(output.resolve()),
                    "logs": list(bridge.transport.logs),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
