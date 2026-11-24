"""Build a single-file preview of the web app with a heat's results embedded.

    python tools/build_preview.py "Load 3 trial" distance out.html a.csv b.csv ...

The page runs the real front-end modules; uploads and re-scoring are
disabled because there is no server behind it.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SKYGAMES_DB"] = ":memory:"

from backend import service  # noqa: E402
from backend.store import Store  # noqa: E402

ORDER = ["dom", "state", "api", "charts", "map", "setup", "rules", "results", "heats", "main"]


def bundle_js() -> str:
    out = []
    for name in ORDER:
        src = (ROOT / "web" / "js" / f"{name}.js").read_text()
        src = re.sub(r'^import .*? from ".*?";\n', "", src, flags=re.M)
        src = re.sub(r"^export ", "", src, flags=re.M)
        out.append(f"// ---- {name}.js\n{src}")
    return "\n".join(out)


def main(name, task, out, *csvs):
    store = Store(":memory:")
    files = [{"flyer": Path(c).stem, "file_name": Path(c).name, "data": Path(c).read_bytes()} for c in csvs]
    hid = store.create_heat(name, task, {}, files)
    payload = service.analyze(store, hid)
    demo = {"meta": service.meta(), "payload": payload, "heats": store.list_heats()}
    html = (ROOT / "web" / "index.html").read_text()
    css = (ROOT / "web" / "css" / "app.css").read_text()
    html = html.replace('<link rel="stylesheet" href="css/app.css">', f"<style>\n{css}\n</style>")
    data = json.dumps(demo, separators=(",", ":"), default=str).replace("</", "<\\/")
    html = html.replace('<script type="module" src="js/main.js"></script>',
                        f"<script>window.SKYGAMES_DEMO = {data};</script>\n<script type=\"module\">\n{bundle_js()}\n</script>")
    Path(out).write_text(html)
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:])
