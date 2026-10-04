"""Generate desktop icons or compare pixels (PNG compression varies by OS)."""
import argparse
import io
from pathlib import Path

from PIL import Image
import resvg_py

ROOT = Path(__file__).resolve().parents[1]


def equivalent(actual, expected, extension):
    with Image.open(io.BytesIO(actual)) as left, Image.open(io.BytesIO(expected)) as right:
        if extension == "ico":
            sizes = right.ico.sizes()
            return left.ico.sizes() == sizes and all(left.ico.getimage(size).convert("RGBA").tobytes() == right.ico.getimage(size).convert("RGBA").tobytes() for size in sizes)
        if extension == "icns":
            sizes = right.info["sizes"]
            return set(left.info["sizes"]) == set(sizes) and all(left.icns.getimage(size).convert("RGBA").tobytes() == right.icns.getimage(size).convert("RGBA").tobytes() for size in sizes)
        return left.size == right.size and left.convert("RGBA").tobytes() == right.convert("RGBA").tobytes()


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
            if not path.exists() or not equivalent(path.read_bytes(), content, path.suffix[1:]):
                raise SystemExit(f"图标不同步，请运行 python scripts/icons.py：{name}")
        else:
            path.write_bytes(content)
    print("Brand icons verified" if args.check else "Brand icons generated")
