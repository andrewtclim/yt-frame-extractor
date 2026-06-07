import io
import img2pdf
from PIL import Image, ImageDraw, ImageFont

_A4_LANDSCAPE = img2pdf.parse_pagesize_rectarg("297mmx210mm")

_FONT_PATH = "/System/Library/Fonts/Helvetica.ttc"


def _get_font(size: int):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except (IOError, OSError):
        return ImageFont.load_default()


def stamp_timestamp(image_path: str, timestamp_str: str) -> bytes:
    """Draw timestamp in bottom-left corner. Returns JPEG bytes."""
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    font_size = max(14, h // 30)
    font = _get_font(font_size)
    padding = max(6, h // 80)

    bbox = draw.textbbox((0, 0), timestamp_str, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = padding * 2
    y = h - th - padding * 3

    # Solid black box behind text for readability
    draw.rectangle(
        [x - padding, y - padding, x + tw + padding, y + th + padding],
        fill=(0, 0, 0),
    )
    draw.text((x, y), timestamp_str, font=font, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def build_pdf(frame_infos: list[dict], stamp_timestamps: bool = True) -> bytes:
    """
    frame_infos: [{path, timestamp_str}, ...]
    Returns PDF bytes, one frame per A4-landscape page.
    """
    images = []
    for info in frame_infos:
        if stamp_timestamps:
            images.append(stamp_timestamp(info["path"], info["timestamp_str"]))
        else:
            with open(info["path"], "rb") as f:
                images.append(f.read())

    layout = img2pdf.get_layout_fun(_A4_LANDSCAPE)
    return img2pdf.convert(*images, layout_fun=layout)
