from __future__ import annotations

from PIL import Image, ImageDraw


def create_tray_icon(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (6, 6, size - 6, size - 6),
        radius=14,
        fill=(34, 113, 209, 255),
    )
    center_x = size // 2
    base_y = size - 18

    for radius, width in ((24, 5), (16, 5), (8, 5)):
        box = (
            center_x - radius,
            base_y - radius,
            center_x + radius,
            base_y + radius,
        )
        draw.arc(box, start=205, end=335, fill=(255, 255, 255, 245), width=width)

    draw.ellipse(
        (center_x - 4, base_y - 2, center_x + 4, base_y + 6),
        fill=(255, 255, 255, 255),
    )
    return image
