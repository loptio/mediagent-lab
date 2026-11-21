"""圖片處理（BR-04、BR-06）：讀取實際格式與寬高、計算並裁切出 Instagram 版本。

- 寬高一律是「顯示時」的寬高：手機直拍的照片像素是橫的，EXIF 記錄要轉 90 度，先依 EXIF 轉正。
- 比例一律用整數比較（4:5 ⇔ 5w = 4h、1.91:1 ⇔ 100w = 191h），避免浮點誤差讓邊界值判斷錯誤。
- 解碼前先看標頭的像素數：檔案很小、像素數卻極大的圖片會在解碼時吃光記憶體，直接拒絕。
"""

import io
import math
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import DomainError

# Instagram 允許的寬高比範圍：4:5（0.8）到 1.91:1，包含兩端
MIN_RATIO = (4, 5)  # 寬:高
MAX_RATIO = (191, 100)
# 解碼後約 3 個位元組／像素：5,000 萬像素約 150 MB，涵蓋一般手機與相機照片
MAX_PIXELS = 50_000_000
# Instagram 版本與原圖同樣受 8,000,000 位元組的限制（BR-04、資料庫限制）
MAX_OUTPUT_BYTES = 8_000_000
# 有些相機的 JPEG 夾帶多張圖（MPO），本質仍是 JPEG
JPEG_FORMATS = {"JPEG", "MPO"}
QUALITY_STEPS = (90, 80, 70, 60, 50, 40)
EXIF_ORIENTATION = 0x0112


def _round_half_up(value: float) -> int:
    """規格的「四捨五入」：0.5 一律進位（Python 的 round 是銀行家捨入，1252.5 會變 1252）。"""
    return math.floor(value + 0.5)


def _too_tall(width: int, height: int) -> bool:
    return width * MIN_RATIO[1] < height * MIN_RATIO[0]


def _too_wide(width: int, height: int) -> bool:
    return width * MAX_RATIO[1] > height * MAX_RATIO[0]


def _not_jpeg() -> DomainError:
    return DomainError(422, "IMAGE_FORMAT_INVALID", "圖片格式必須是 JPEG，且檔案完整")


def _too_large() -> DomainError:
    return DomainError(422, "IMAGE_DIMENSION_INVALID", "圖片像素太多（上限 5,000 萬像素），請縮小後再上傳")


def _open_upright(data: bytes) -> Image.Image:
    """開啟並完整解碼，依 EXIF 轉正。格式不對、像素過多或檔案不完整時拋出 422。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in JPEG_FORMATS:
                raise _not_jpeg()
            if image.width * image.height > MAX_PIXELS:
                raise _too_large()
            image.load()  # 完整解碼：截斷的檔案在這裡就會被發現
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _too_large() from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise _not_jpeg() from exc
    return ImageOps.exif_transpose(image)


def inspect(data: bytes) -> tuple[int, int]:
    """讀取實際格式（不信任副檔名或 Content-Type），回傳顯示時的（寬, 高）。"""
    with _open_upright(data) as image:
        return image.size


def instagram_ready(data: bytes) -> bool:
    """原圖能不能直接給 Instagram：Instagram 不接受 MPO，也不保證依 EXIF 方向轉正。
    呼叫前已經通過 inspect，這裡只讀標頭。"""
    with Image.open(io.BytesIO(data)) as image:
        return image.format == "JPEG" and image.getexif().get(EXIF_ORIENTATION, 1) == 1


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
    """從（轉正後的）圖片中間裁出 width×height，輸出 JPEG；超過大小上限時逐步降低品質。"""
    with _open_upright(data) as image:
        icc_profile = image.info.get("icc_profile")  # 保留色彩描述檔，廣色域照片才不會變暗
        left = (image.width - width) // 2
        top = (image.height - height) // 2
        cropped = image.crop((left, top, left + width, top + height))  # 先裁再轉色彩，處理的像素較少
        if cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        for quality in QUALITY_STEPS:
            buffer = io.BytesIO()
            cropped.save(buffer, format="JPEG", quality=quality, icc_profile=icc_profile)
            if buffer.tell() <= MAX_OUTPUT_BYTES:
                return buffer.getvalue()
        raise DomainError(422, "IMAGE_TOO_LARGE", "Instagram 版本壓縮後仍超過 8 MB，請縮小圖片後再上傳")
