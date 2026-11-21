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


def with_orientation(width, height, orientation=6) -> bytes:
    """手機直拍：像素是橫的，EXIF 記錄顯示時要轉 90 度。"""
    image = Image.new("RGB", (width, height), (10, 10, 10))
    exif = image.getexif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_exif_orientation_is_applied_to_size_and_crop():
    data = with_orientation(4000, 1500)  # 顯示為 1500×4000 的直式照片

    assert images.inspect(data) == (1500, 4000)
    assert images.instagram_size(1500, 4000) == (1500, 1875)
    cropped = Image.open(io.BytesIO(images.crop_center(data, 1500, 1875)))
    assert cropped.size == (1500, 1875)


def with_header_size(data: bytes, width: int, height: int) -> bytes:
    """把 JPEG 標頭（SOF0）裡的寬高改大：模擬像素數極大、檔案卻很小的圖片。"""
    index = data.index(b"\xff\xc0")
    patched = bytearray(data)
    patched[index + 5 : index + 7] = height.to_bytes(2, "big")
    patched[index + 7 : index + 9] = width.to_bytes(2, "big")
    return bytes(patched)


@pytest.mark.parametrize("size", [(20000, 10000), (9000, 6000)])
def test_too_many_pixels_is_rejected_before_decoding(size):
    with pytest.raises(DomainError) as error:
        images.inspect(with_header_size(jpeg(100, 100), *size))
    assert (error.value.status_code, error.value.code) == (422, "IMAGE_DIMENSION_INVALID")


def test_truncated_jpeg_is_rejected():
    data = jpeg(800, 600)

    with pytest.raises(DomainError) as error:
        images.inspect(data[: len(data) // 2])
    assert error.value.code == "IMAGE_FORMAT_INVALID"


def test_camera_jpeg_with_multi_picture_data_is_accepted():
    first, second = Image.new("RGB", (640, 480)), Image.new("RGB", (320, 240))
    buffer = io.BytesIO()
    first.save(buffer, format="MPO", save_all=True, append_images=[second])

    assert images.inspect(buffer.getvalue()) == (640, 480)


def test_instagram_version_stays_within_the_size_limit(monkeypatch):
    """重新壓縮的裁切版本超過上限時，逐步降低品質直到符合（不讓資料庫限制變成 500）。"""
    import os

    noisy = Image.frombytes("RGB", (600, 1200), os.urandom(600 * 1200 * 3))
    buffer = io.BytesIO()
    noisy.save(buffer, format="JPEG", quality=95)
    best_quality = len(images.crop_center(buffer.getvalue(), 600, 750))
    limit = int(best_quality * 0.7)
    monkeypatch.setattr(images, "MAX_OUTPUT_BYTES", limit)

    cropped = images.crop_center(buffer.getvalue(), 600, 750)

    assert len(cropped) <= limit
    assert Image.open(io.BytesIO(cropped)).size == (600, 750)
