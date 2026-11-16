# /// script
# requires-python = ">=3.9"
# dependencies = ["Pillow>=11,<13", "qrcode>=8,<9"]
# ///
"""Render the editable, 1440 × 1920 WeChat launch poster.

Run with: uv run tools/make_social_poster.py
On other systems, pass --font /path/to/a/Chinese/font.ttf.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import qrcode


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/HerbiusYang/VIGILYX-Training-Data"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=Path("/System/Library/Fonts/STHeiti Medium.ttc"))
    parser.add_argument("--out", type=Path, default=PROJECT / "docs/assets/wechat-moments.png")
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error("Use --font to select an installed Chinese font.")
    records = json.loads((PROJECT / "data/corpus.json").read_text(encoding="utf-8"))

    width, height = 1440, 1920
    canvas = Image.new("RGB", (width, height), "#0a1e28")
    glow = Image.new("RGBA", canvas.size)
    g = ImageDraw.Draw(glow)
    g.ellipse((760, -380, 1740, 760), fill=(0, 128, 112, 70))
    g.ellipse((-480, 1040, 700, 2130), fill=(0, 94, 85, 60))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(180)))
    white, muted, green = "#f2f7f7", "#9bb5bd", "#8ae9c4"
    grid = Image.new("RGBA", canvas.size)
    grid_draw = ImageDraw.Draw(grid)
    for x in range(0, width, 80):
        grid_draw.line((x, 0, x, height), fill=(161, 218, 210, 8))
    for y in range(0, height, 80):
        grid_draw.line((0, y, width, y), fill=(161, 218, 210, 8))
    canvas = Image.alpha_composite(canvas, grid)
    draw = ImageDraw.Draw(canvas)

    fonts = {}

    def text(x, y, value, size, color=white):
        if size not in fonts:
            fonts[size] = ImageFont.truetype(str(args.font), size)
        draw.text((x, y), value, font=fonts[size], fill=color, anchor="lt", stroke_width=0)

    # Envelope mark follows the local viewer's existing brand geometry.
    draw.rounded_rectangle((96, 92, 164, 160), radius=18, fill="#12584f")
    draw.rounded_rectangle((110, 112, 150, 141), radius=3, outline=green, width=3)
    draw.line((111, 114, 130, 128, 149, 114), fill=green, width=3)
    text(186, 93, "VIGILYX", 48)
    text(188, 146, "TRAINING DATA", 22, muted)
    draw.rounded_rectangle((1055, 103, 1344, 153), radius=25, outline="#3c6b65", width=1)
    text(1082, 119, "OPEN SOURCE / MIT", 22, green)

    text(100, 265, "为邮件安全研究而做", 30, muted)
    text(92, 340, "邮件安全训练语料", 104)
    text(92, 474, "开源了。", 130, green)
    text(100, 664, "钓鱼 · 身份冒用 · 业务流程篡改 · 商业邮件诈骗", 30, "#c0d3d7")

    draw.rounded_rectangle((96, 760, 1344, 1004), radius=30, fill="#14343c", outline="#2b5158", width=2)
    text(135, 797, f"{len(records):,}", 130, green)
    text(586, 878, "条邮件样本", 34)
    draw.line((865, 808, 865, 956), fill="#31555b", width=2)
    text(915, 819, "中文 / 英文 / 双语", 30)
    text(915, 887, "正常与威胁对照", 28, muted)

    features = [
        ("01", "JSON 训练语料", "分类输入、标签与证据分开保存"),
        ("02", "本地语料工作台", "搜索筛选 · 盲测 · 证据与来源查看"),
        ("03", "生成与校验 Skill", "来源取材 · 场景规划 · 结构检查"),
    ]
    for index, (number, title, description) in enumerate(features):
        y = 1086 + index * 138
        text(102, y + 5, number, 25, green)
        text(180, y, title, 39)
        text(182, y + 61, description, 27, muted)
        if index < 2:
            draw.line((180, y + 110, 1336, y + 110), fill="#24434b", width=1)

    draw.line((96, 1538, 1344, 1538), fill="#36545c", width=2)
    text(100, 1594, "现在，GitHub 见。", 51)
    text(102, 1683, "HerbiusYang /", 28, muted)
    text(100, 1732, "VIGILYX-Training-Data", 38, green)
    text(103, 1801, "扫码查看源码、数据与使用说明", 25, muted)

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
    qr.add_data(REPOSITORY)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="#0a1e28", back_color="white").convert("RGBA")
    # Keep integer-sized QR modules to preserve readability after sharing.
    canvas.alpha_composite(qr_image, (1344 - qr_image.width, 1580))
    text(101, 1873, "防御训练语料，含来源改编与历史合成样本；并非截获原始邮件。", 20, "#78979f")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(args.out, optimize=True, dpi=(144, 144))
    print(args.out)


if __name__ == "__main__":
    main()
