"""圖片處理（BR-04、BR-06）：讀取格式與寬高、Instagram 版本的大小與從中間裁切。"""

import io

import pytest
from PIL import Image

from app.core.errors import DomainError
from app.m3_posts import images


def jpeg(width: int, height: int, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((1080, 1080), (1080, 1080)),  # 1:1，不裁切
        ((1080, 1350), (1080, 1350)),  # 恰為 4:5
        ((1910, 1000), (1910, 1000)),  # 恰為 1.91:1
        ((1080, 1920), (1080, 1350)),  # 9:16 → 4:5
        ((2000, 1000), (1910, 1000)),  # 2:1 → 1.91:1
        ((1001, 2000), (1001, 1251)),  # 1251.25 四捨五入為 1251，比例符合
        ((1002, 2000), (1002, 1252)),  # 1252.5 四捨五入為 1253 超出範圍，減 1
        ((3000, 1001), (1911, 1001)),  # 1911.91 四捨五入為 1912 超出範圍，減 1
    ],
)
def test_instagram_size_follows_br06(size, expected):
    assert images.instagram_size(*size) == expected


def test_inspect_reads_jpeg_dimensions():
    assert images.inspect(jpeg(1080, 1920)) == (1080, 1920)


@pytest.mark.parametrize("data", [jpeg(100, 100, "PNG"), b"not an image at all"])
def test_inspect_rejects_anything_but_jpeg(data):
    with pytest.raises(DomainError) as error:
        images.inspect(data)
    assert (error.value.status_code, error.value.code) == (422, "IMAGE_FORMAT_INVALID")


def test_crop_center_keeps_the_middle():
    original = Image.new("RGB", (1080, 1920), (0, 0, 255))
    original.paste((255, 0, 0), (0, 285, 1080, 1635))  # 中間 1080×1350 是紅色
    buffer = io.BytesIO()
    original.save(buffer, format="JPEG", quality=95)

    cropped = Image.open(io.BytesIO(images.crop_center(buffer.getvalue(), 1080, 1350)))

    assert cropped.size == (1080, 1350)
    assert cropped.format == "JPEG"
    red, green, blue = cropped.getpixel((540, 5))
    assert red > 200 and blue < 60  # 上緣已經是紅色，代表裁掉的是上下各 285 像素
