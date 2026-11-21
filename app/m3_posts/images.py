"""圖片處理（BR-04、BR-06）：讀取實際格式與寬高、計算並裁切出 Instagram 版本。

比例一律用整數比較（4:5 ⇔ 5w = 4h、1.91:1 ⇔ 100w = 191h），避免浮點誤差讓邊界值判斷錯誤。
"""

import io
import math

from PIL import Image, UnidentifiedImageError

from app.core.errors import DomainError

# Instagram 允許的寬高比範圍：4:5（0.8）到 1.91:1，包含兩端
MIN_RATIO = (4, 5)  # 寬:高
MAX_RATIO = (191, 100)


def _round_half_up(value: float) -> int:
    """規格的「四捨五入」：0.5 一律進位（Python 的 round 是銀行家捨入，1252.5 會變 1252）。"""
    return math.floor(value + 0.5)


def _too_tall(width: int, height: int) -> bool:
    return width * MIN_RATIO[1] < height * MIN_RATIO[0]


def _too_wide(width: int, height: int) -> bool:
    return width * MAX_RATIO[1] > height * MAX_RATIO[0]


def inspect(data: bytes) -> tuple[int, int]:
    """讀取實際格式（不信任副檔名或 Content-Type），回傳（寬, 高）；不是 JPEG 時拋出 422。"""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG":
                raise _not_jpeg()
            return image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _not_jpeg() from exc


def _not_jpeg() -> DomainError:
    return DomainError(422, "IMAGE_FORMAT_INVALID", "圖片格式必須是 JPEG")


def instagram_size(width: int, height: int) -> tuple[int, int]:
    """BR-06：比例在 4:5～1.91:1 之間時不變；過高時從中間裁成 4:5，過寬時裁成 1.91:1。

    只調整被裁的那一邊；被裁邊長先四捨五入，若比例仍超出範圍，每次減 1 像素直到符合。
    """
    if _too_tall(width, height):
        new_height = _round_half_up(width * MIN_RATIO[1] / MIN_RATIO[0])
        while _too_tall(width, new_height):
            new_height -= 1
        return width, new_height
    if _too_wide(width, height):
        new_width = _round_half_up(height * MAX_RATIO[0] / MAX_RATIO[1])
        while _too_wide(new_width, height):
            new_width -= 1
        return new_width, height
    return width, height


def crop_center(data: bytes, width: int, height: int) -> bytes:
    """從圖片中間裁出 width×height，輸出 JPEG。"""
    with Image.open(io.BytesIO(data)) as image:
        left = (image.width - width) // 2
        top = (image.height - height) // 2
        cropped = image.convert("RGB").crop((left, top, left + width, top + height))
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()
