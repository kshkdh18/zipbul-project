from __future__ import annotations

import argparse
import functools
import os
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Keep linear algebra from oversubscribing a Mac that is also decoding and rendering.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "2")


def main():
    parser = argparse.ArgumentParser(description="Depth-verified Mac texture postprocessing for Zipscan")
    commands = parser.add_subparsers(dest="command", required=True)
    bake_parser = commands.add_parser("bake", help="Create textured GLB, OBJ/MTL and an offline viewer")
    bake_parser.add_argument("input", type=Path)
    bake_parser.add_argument("--output", type=Path, required=True)
    bake_parser.add_argument("--profile", choices=["quality", "compact"], default="quality")
    bake_parser.add_argument("--interval", type=float)
    bake_parser.add_argument("--image-size", type=int)
    bake_parser.add_argument("--atlas-size", type=int, default=4096)
    bake_parser.add_argument("--max-distance", type=float, default=5)
    bake_parser.add_argument("--depth-tolerance", type=float, default=0.12)
    bake_parser.add_argument("--min-confidence", type=int, choices=[1, 2], default=1)
    view_parser = commands.add_parser("view", help="Serve a finished result on localhost; no upload")
    view_parser.add_argument("directory", type=Path)
    view_parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    if args.command == "bake":
        from .pipeline import bake
        try:
            bake(args.input, args.output, interval=args.interval if args.interval is not None else (0.75 if args.profile == "quality" else 1.5), image_size=args.image_size if args.image_size is not None else (1920 if args.profile == "quality" else 1024), atlas_size=args.atlas_size, max_distance=args.max_distance, depth_tolerance=args.depth_tolerance, min_confidence=args.min_confidence, log=lambda text: print(text, flush=True))
        except (ValueError, OSError) as error:
            parser.exit(1, f"Texture processing failed: {error}\n")
    else:
        directory = args.directory.resolve()
        if not (directory / "viewer.html").is_file() or not (directory / "report.json").is_file():
            parser.error("Directory is not a finished texture result")
        # The hidden source/cache folder is never served to a browser.
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import unquote, urlsplit
                parts = Path(unquote(urlsplit(self.path).path)).parts
                if any(part.startswith(".") for part in parts):
                    self.send_error(403); return
                super().do_GET()
            def list_directory(self, path):
                self.send_error(403)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Handler, directory=str(directory)))
        print(f"Viewer: http://127.0.0.1:{server.server_port}/viewer.html", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
