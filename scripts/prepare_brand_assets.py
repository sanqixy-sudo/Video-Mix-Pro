from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


OFF_WHITE = (237, 237, 239, 255)
DARK_NAVY = (4, 20, 47, 255)


def smoothstep(value: np.ndarray, low: float, high: float) -> np.ndarray:
    scaled = np.clip((value - low) / (high - low), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def extract_mark(source: Path) -> Image.Image:
    image = Image.open(source).convert("RGB")
    # The supplied render is 3:2 with the brand mark centered. Limit the work
    # area before keying so the decorative page background cannot leak into the
    # icon. The ratios keep the operation stable if a same-composition export is
    # supplied at another resolution.
    width, height = image.size
    crop_box = (
        round(width * 0.34),
        round(height * 0.15),
        round(width * 0.66),
        round(height * 0.75),
    )
    image = image.crop(crop_box)
    pixels = np.asarray(image, dtype=np.float32)

    chroma = pixels.max(axis=2) - pixels.min(axis=2)
    alpha = smoothstep(chroma, 22.0, 112.0)
    alpha = np.power(alpha, 0.90)
    alpha[alpha < 0.04] = 0.0

    ys, xs = np.where(alpha >= 0.12)
    if not len(xs):
        raise RuntimeError(f"Could not isolate foreground from {source}")
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    pad_x = max(12, int((right - left) * 0.035))
    pad_y = max(12, int((bottom - top) * 0.05))
    left, right = max(0, left - pad_x), min(image.width, right + pad_x)
    top, bottom = max(0, top - pad_y), min(image.height, bottom + pad_y)

    rgba = np.dstack((pixels, alpha * 255.0)).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA").crop((left, top, right, bottom))


def square_canvas(image: Image.Image, padding_ratio: float = 0.10) -> Image.Image:
    side = max(image.width, image.height)
    padding = max(20, int(side * padding_ratio))
    canvas = Image.new("RGBA", (side + padding * 2, side + padding * 2), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
    return canvas


def font_path() -> Path:
    candidates = (
        Path("C:/Windows/Fonts/seguisb.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("No suitable Windows UI font was found")


def make_wordmark(mark: Image.Image, color: tuple[int, int, int, int]) -> Image.Image:
    target_height = 260
    mark_copy = mark.copy()
    mark_copy.thumbnail((target_height, target_height), Image.Resampling.LANCZOS)
    font = ImageFont.truetype(str(font_path()), 132)
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)
    text_box = probe_draw.textbbox((0, 0), "Video Mix Pro", font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    gap = 34
    padding = 18
    canvas = Image.new("RGBA", (mark_copy.width + gap + text_width + padding * 2, target_height + padding * 2), (0, 0, 0, 0))
    canvas.alpha_composite(mark_copy, (padding, padding + (target_height - mark_copy.height) // 2))
    draw = ImageDraw.Draw(canvas)
    text_x = padding + mark_copy.width + gap
    text_y = padding + (target_height - text_height) // 2 - text_box[1]
    draw.text((text_x, text_y), "Video Mix Pro", font=font, fill=color)
    return canvas


def save_resized(image: Image.Image, path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resized = image.resize(size, Image.Resampling.LANCZOS)
    resized.save(path, optimize=True)


def alpha_summary(path: Path) -> str:
    image = Image.open(path).convert("RGBA")
    alpha = np.asarray(image)[:, :, 3]
    corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]
    coverage = float(np.count_nonzero(alpha)) / float(alpha.size)
    return f"{path}: {image.width}x{image.height}, alpha_coverage={coverage:.3f}, corners={corners}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Video Mix Pro brand assets from supplied raster references.")
    parser.add_argument("--mark-source", type=Path, required=True)
    parser.add_argument("--wordmark-source", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    desktop_assets = project_root / "desktop" / "src" / "assets"
    tauri_icons = project_root / "desktop" / "src-tauri" / "icons"
    web_brand = project_root / "server" / "static" / "brand"

    # Open the horizontal reference as an explicit input validation step. Its
    # icon/text proportions guide the generated wordmark, while the clean text
    # is rendered locally so it remains sharp on both light and dark surfaces.
    Image.open(args.wordmark_source).verify()
    mark = square_canvas(extract_mark(args.mark_source), padding_ratio=0.08)
    wordmark = make_wordmark(mark, DARK_NAVY)
    wordmark_light = make_wordmark(mark, OFF_WHITE)

    save_resized(mark, desktop_assets / "brand-mark.png", (256, 256))
    save_resized(wordmark_light, desktop_assets / "brand-horizontal.png", (640, round(640 * wordmark.height / wordmark.width)))

    save_resized(mark, tauri_icons / "32x32.png", (32, 32))
    save_resized(mark, tauri_icons / "128x128.png", (128, 128))
    save_resized(mark, tauri_icons / "128x128@2x.png", (256, 256))
    save_resized(mark, tauri_icons / "icon.png", (512, 512))
    icon = mark.resize((256, 256), Image.Resampling.LANCZOS)
    icon.save(tauri_icons / "icon.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    save_resized(mark, web_brand / "logo-mark.png", (512, 512))
    save_resized(wordmark, web_brand / "logo-horizontal-dark.png", (1024, round(1024 * wordmark.height / wordmark.width)))
    save_resized(wordmark_light, web_brand / "logo-horizontal.png", (1024, round(1024 * wordmark.height / wordmark.width)))
    save_resized(mark, web_brand / "favicon-64.png", (64, 64))
    favicon = mark.resize((256, 256), Image.Resampling.LANCZOS)
    favicon.save(web_brand / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    for output in (
        desktop_assets / "brand-mark.png",
        desktop_assets / "brand-horizontal.png",
        tauri_icons / "icon.png",
        web_brand / "logo-mark.png",
        web_brand / "logo-horizontal.png",
        web_brand / "logo-horizontal-dark.png",
        web_brand / "favicon-64.png",
    ):
        print(alpha_summary(output))


if __name__ == "__main__":
    main()
