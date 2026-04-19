"""把 PNG 图标裁成正方形并导出为 Windows .ico。

支持自动从 assets/ 目录寻找最新的 PNG（按修改时间），
也可以通过命令行参数显式指定源文件。
"""
from pathlib import Path
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIRS = [
    ROOT / "assets",
    Path(r"C:\Users\meteor\.cursor\projects\c-Users-meteor-Projects-cable-commission-tool\assets"),
]
DST_PNG = ROOT / "dist" / "cable-commission-app" / "app.png"
DST_ICO = ROOT / "dist" / "cable-commission-app" / "app.ico"


def find_latest_png() -> Path:
    pngs: list[Path] = []
    for d in ASSETS_DIRS:
        if d.exists():
            pngs.extend(p for p in d.iterdir() if p.suffix.lower() == ".png")
    if not pngs:
        raise SystemExit("未找到任何 PNG 文件")
    pngs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pngs[0]


def crop_to_square(img: Image.Image, bg=(255, 255, 255, 255)) -> Image.Image:
    """裁掉多余白边并补成正方形，背景透明。"""
    rgba = img.convert("RGBA")

    # 先用 alpha 通道找内容范围；若图片本来不透明，则用近白阈值法找内容
    bbox = rgba.getbbox()
    if bbox is None:
        return rgba

    cropped = rgba.crop(bbox)
    w, h = cropped.size
    side = int(max(w, h) * 1.10)  # 留 5% 边距

    canvas = Image.new("RGBA", (side, side), bg)
    canvas.paste(cropped, ((side - w) // 2, (side - h) // 2), cropped)
    return canvas


def main() -> None:
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    else:
        src = find_latest_png()

    print(f"源图标: {src}")
    img = Image.open(src)
    img = crop_to_square(img, bg=(255, 255, 255, 255))

    DST_PNG.parent.mkdir(parents=True, exist_ok=True)
    img.resize((512, 512), Image.LANCZOS).save(DST_PNG, format="PNG")

    sizes = [(256, 256), (128, 128), (96, 96), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(DST_ICO, format="ICO", sizes=sizes)
    print(f"OK -> {DST_ICO}  ({DST_ICO.stat().st_size:,} bytes)")
    print(f"OK -> {DST_PNG}  ({DST_PNG.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
