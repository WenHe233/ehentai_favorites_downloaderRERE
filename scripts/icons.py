"""Generate all desktop icons from the favicon SVG, or verify checked-in bytes."""
import argparse
import io
from pathlib import Path

from PIL import Image
import resvg_py

ROOT = Path(__file__).resolve().parents[1]


def generated():
    png = resvg_py.svg_to_bytes(svg_path=str(ROOT / "frontend/public/efdrr-icon.svg"), width=1024, height=1024)
    icon = Image.open(io.BytesIO(png)).convert("RGBA")
    result = {"icon.png": png}
    for extension, sizes in (("ico", [(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]), ("icns", None)):
        stream = io.BytesIO()
        icon.save(stream, format=extension.upper(), **({"sizes": sizes} if sizes else {}))
        result["icon." + extension] = stream.getvalue()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, content in generated().items():
        path = ROOT / "desktop" / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(f"图标不同步，请运行 python scripts/icons.py：{name}")
        else:
            path.write_bytes(content)
    print("Brand icons verified" if args.check else "Brand icons generated")
