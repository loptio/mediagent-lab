"""M3 貼文編輯：建立、取得、列表、修改、刪除、複製為新草稿、預覽、附加與移除圖片。"""

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, auth, clock, publish_rules
from app.core.enums import AuditAction, AuthStatus, Platform, PostStatus, Role, TargetType
from app.core.errors import DomainError, not_found
from app.core.media import get_storage
from app.core.models import MediaFile, PlatformAccount, Post, PostImage, UserAccount
from app.core.platforms import effective_auth_status, get_adapter
from app.m4_scheduling import lifecycle

from . import images, repository
from .schemas import (
    ImageOut,
    PostListItem,
    PostOut,
    PostPage,
    PreviewImage,
    PreviewItem,
    PreviewOut,
    TargetOut,
    UserRef,
)

logger = logging.getLogger("mediagent.posts")

PAGE_SIZES = (20, 50, 100)
MAX_IMAGE_BYTES = 8_000_000  # BR-04
EDITABLE_STATUSES = (PostStatus.DRAFT, PostStatus.SCHEDULED)


def _targets(accounts: list[PlatformAccount]) -> list[TargetOut]:
    now = clock.now()
    return [
        TargetOut(
            id=account.id,
            platform=account.platform,
            account_name=account.account_name,
            auth_status=effective_auth_status(account, now),
        )
        for account in accounts
    ]


def image_out(image: PostImage | None) -> ImageOut | None:
    if image is None:
        return None
    original, instagram = image.original, image.instagram
    return ImageOut(
        format=original.format,
        size_bytes=original.size_bytes,
        width=original.width,
        height=original.height,
        public_url=original.public_url,
        ig_public_url=instagram.public_url,
        ig_width=instagram.width,
        ig_height=instagram.height,
        ig_cropped=image.cropped,
    )


def _to_out(db: Session, post: Post) -> PostOut:
    return PostOut(
        id=post.id,
        content=post.content,
        status=post.status,
        scheduled_at=post.scheduled_at,
        scheduled_by=post.scheduled_by,
        creator=UserRef(id=post.creator.id, name=post.creator.name),
        created_at=post.created_at,
        image=image_out(post.image),
        targets=_targets(repository.targets_of(db, [post.id])[post.id]),
    )


def create_post(db: Session, user: UserAccount, content: str) -> PostOut:
    if not content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")
    post = repository.create(db, user.id, content)
    db.commit()
    return get_post(db, post.id)


def get_post(db: Session, post_id: int) -> PostOut:
    post = repository.get_active(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    return _to_out(db, post)


def list_posts(db: Session, status: str | None, page: int, page_size: int) -> PostPage:
    if page < 1 or page_size not in PAGE_SIZES:
        raise DomainError(400, "VALIDATION_ERROR", "page 必須大於 0，page_size 只能是 20、50、100")
    if status is not None and status not in PostStatus.__members__:
        raise DomainError(400, "VALIDATION_ERROR", "status 不是有效的貼文狀態")

    total = repository.count(db, status)
    posts = repository.list_page(db, status, (page - 1) * page_size, page_size)
    targets = repository.targets_of(db, [post.id for post in posts])
    total_pages = (total + page_size - 1) // page_size
    return PostPage(
        items=[
            PostListItem(
                id=post.id,
                content=post.content,
                status=post.status,
                scheduled_at=post.scheduled_at,
                created_at=post.created_at,
                creator=UserRef(id=post.creator.id, name=post.creator.name),
                has_image=post.image is not None,
                targets=_targets(targets[post.id]),
            )
            for post in posts
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


def _editable_post(db: Session, user: UserAccount, post_id: int) -> Post:
    """鎖定並取得可以修改或刪除的貼文（BR-13、BR-18）。"""
    post = repository.get_active_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, post.creator_id, Role.PUBLISHER)
    if post.status not in EDITABLE_STATUSES:
        raise DomainError(409, "POST_NOT_EDITABLE", "只有草稿與已排程的貼文可以修改或刪除")
    return post


def update_post(db: Session, user: UserAccount, post_id: int, content: str) -> PostOut:
    """修改貼文內容（FR-12）。已排程貼文以新內容檢查發佈限制，成功後維持已排程、時間不變（BR-24）。"""
    post = _editable_post(db, user, post_id)
    if not content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")
    post.content = content
    if post.status == PostStatus.SCHEDULED:
        # BR-24：以新內容檢查發佈限制（BR-02、05、07、08），包含目標的授權狀態。
        # 不符合時拋出錯誤，交易不會 commit，內容維持原樣
        publish_rules.check(post, repository.targets_of(db, [post.id])[post.id], clock.now())
    db.commit()
    return get_post(db, post.id)


def delete_post(db: Session, user: UserAccount, post_id: int) -> None:
    """刪除貼文（FR-13）：軟刪除，發佈紀錄、變更歷程與稽核都保留，仍可用原 ID 查看發佈結果（BR-35）。"""
    post = _editable_post(db, user, post_id)
    if post.status == PostStatus.SCHEDULED:
        lifecycle.on_post_deleting(db, post, user)  # 待發佈紀錄改為已取消
    post.deleted_at = clock.now()
    orphaned = _detach_image(db, post)
    db.commit()
    _delete_files(orphaned)


def copy_post(db: Session, user: UserAccount, post_id: int) -> PostOut:
    """複製為新草稿（FR-27、BR-36）：任何狀態都可以複製；新草稿沒有目標與發佈紀錄，建立者是執行複製的人。"""
    source = repository.get_active(db, post_id)
    if source is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, source.creator_id, Role.PUBLISHER)
    draft = repository.create(db, user.id, source.content)
    if source.image is not None:
        # 複本與來源共用同一份圖片檔案（architecture 決策 20），最後一個引用拿掉時才刪檔
        db.add(
            PostImage(
                post_id=draft.id,
                original_media_id=source.image.original_media_id,
                ig_media_id=source.image.ig_media_id,
            )
        )
    audit.write(
        db,
        action=AuditAction.POST_COPY,
        actor=user,
        target_type=TargetType.POST,
        target_id=source.id,
        related_post_id=draft.id,  # 《資料模型》audit_log：複製時記錄新草稿
    )
    db.commit()
    return get_post(db, draft.id)


def preview(db: Session, post_id: int) -> PreviewOut:
    """每個已選目標各一筆預覽（FR-20、BR-46）。只讀資料、不呼叫平台；授權已失效的目標照常顯示並標示。"""
    post = repository.get_active(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    accounts = repository.targets_of(db, [post.id])[post.id]
    if not accounts:
        raise DomainError(422, "NO_TARGET", "請至少選擇一個目標平台帳號才能預覽")

    items = []
    for account, target in zip(accounts, _targets(accounts), strict=True):
        adapter = get_adapter(account.platform)
        count = adapter.count_chars(post.content)
        limit = adapter.capabilities.max_text_length
        warnings = []
        if count > limit:
            warnings.append("CONTENT_TOO_LONG")
        image = None
        if post.image is not None:
            # Instagram 預覽裁切後的版本，Threads 與 Discord 預覽原圖
            on_instagram = account.platform == Platform.INSTAGRAM
            media = post.image.instagram if on_instagram else post.image.original
            image = PreviewImage(
                url=media.public_url,
                width=media.width,
                height=media.height,
                variant="instagram" if on_instagram else "original",
            )
            if on_instagram and post.image.cropped:
                warnings.append("IMAGE_CROPPED")
        if target.auth_status == AuthStatus.INVALID:
            warnings.append("AUTH_INVALID")
        items.append(
            PreviewItem(
                platform_account=target,
                text=post.content,
                char_count=count,
                char_limit=limit,
                image=image,
                warnings=warnings,
            )
        )
    return PreviewOut(items=items)


# ---------- 圖片（FR-11、BR-03～BR-06） ----------


def _store(data: bytes, width: int, height: int) -> MediaFile:
    storage = get_storage()
    key = storage.save(data)
    return MediaFile(
        storage_key=key,
        public_url=storage.url(key),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        width=width,
        height=height,
    )


def _instagram_version(data: bytes, size: tuple[int, int], ig_size: tuple[int, int]) -> bytes | None:
    """需要裁切，或原圖是 Instagram 不收的格式（MPO、要依 EXIF 轉正）時，產生重新編碼的版本；
    可以直接用原圖時回傳 None。只是重新編碼、沒有裁切的版本超過大小上限時也退回原圖：
    不讓只發 Threads、Discord 的貼文因此無法附圖（Instagram 若不收，發佈時會回報原因）。"""
    if ig_size != size:
        return images.crop_center(data, *ig_size)
    if images.instagram_ready(data):
        return None
    try:
        return images.crop_center(data, *ig_size)
    except DomainError as error:
        if error.code != "IMAGE_TOO_LARGE":
            raise
        return None


def attach_image(db: Session, user: UserAccount, post_id: int, data: bytes) -> ImageOut:
    """附加一張 JPEG（最多 8,000,000 位元組），同時產生 Instagram 版本（BR-03、BR-04、BR-06）。"""
    post = _editable_post(db, user, post_id)
    if post.image is not None:
        raise DomainError(409, "IMAGE_ALREADY_ATTACHED", "每則貼文最多一張圖片，請先移除原本的圖片")
    if len(data) > MAX_IMAGE_BYTES:
        raise DomainError(422, "IMAGE_TOO_LARGE", "圖片不可超過 8 MB（8,000,000 位元組）")
    width, height = images.inspect(data)
    ig_width, ig_height = images.instagram_size(width, height)

    stored: list[MediaFile] = []
    try:
        original = _store(data, width, height)
        stored.append(original)
        ig_data = _instagram_version(data, (width, height), (ig_width, ig_height))
        if ig_data is not None:
            instagram = _store(ig_data, ig_width, ig_height)
            stored.append(instagram)
        else:
            instagram = original  # 比例已符合：Instagram 版本就是原圖
        db.add_all(stored)
        db.flush()
        image = PostImage(post_id=post.id, original_media_id=original.id, ig_media_id=instagram.id)
        db.add(image)
        db.commit()
    except Exception:
        db.rollback()
        _delete_files([media.storage_key for media in stored])  # 沒有寫進資料庫的檔案不留下
        raise
    db.refresh(post)
    return image_out(post.image)


def remove_image(db: Session, user: UserAccount, post_id: int) -> None:
    """移除圖片；目標含 Instagram 時不可移除（BR-05）。圖片檔案沒有其他貼文使用時一併刪除。"""
    post = _editable_post(db, user, post_id)
    if post.image is None:
        raise not_found("這則貼文沒有圖片")
    targets = repository.targets_of(db, [post.id])[post.id]
    if any(account.platform == Platform.INSTAGRAM for account in targets):
        raise DomainError(
            409, "IMAGE_REQUIRED_BY_INSTAGRAM", "目標含 Instagram 時不能移除圖片，請先取消選擇 Instagram"
        )
    orphaned = _detach_image(db, post)
    db.commit()
    _delete_files(orphaned)


def _detach_image(db: Session, post: Post) -> list[str]:
    """拿掉貼文與圖片的關聯；回傳不再被任何貼文使用、應該刪除的檔案（提交後再刪）。"""
    image = db.scalar(select(PostImage).where(PostImage.post_id == post.id))
    if image is None:
        return []
    media_ids = {image.original_media_id, image.ig_media_id}
    # 先鎖定圖片檔案的資料列：原貼文與複本同時移除圖片時，第二個會等第一個提交後再判斷還有沒有人使用
    db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids)).order_by(MediaFile.id).with_for_update()).all()
    db.delete(image)
    db.flush()
    orphaned = []
    for media_id in media_ids:
        still_used = db.scalar(
            select(PostImage.id).where(
                (PostImage.original_media_id == media_id) | (PostImage.ig_media_id == media_id)
            )
        )
        if still_used is None:
            media = db.get(MediaFile, media_id)
            orphaned.append(media.storage_key)
            db.delete(media)
    db.flush()
    return orphaned


def _delete_files(keys: list[str]) -> None:
    """資料庫已提交後才刪檔；刪不掉只記錄下來（留下沒人用的檔案），不讓已完成的操作回報失敗。"""
    storage = get_storage()
    for key in keys:
        try:
            storage.delete(key)
        except Exception as exc:
            logger.warning("could not delete media %s: %s", key, type(exc).__name__)
