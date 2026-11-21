"""全部 ORM models：對應《資料模型》第 5 節的 13 張表。

資料表名稱與 spec/erm.dbml 相同（單數）。列舉值存英文代碼，以 CHECK 限制。
與《資料模型》的差異（foundation-plan）：
- D-04：post 以 deleted_at 軟刪除；publish_record.post_id 是真正的外鍵。
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import clock
from .db import Base
from .enums import (
    FINAL_POST_STATUSES,
    ActorType,
    AuditAction,
    AuthStatus,
    FailureReason,
    HistoryReason,
    ImageVariant,
    LoginFailureReason,
    Platform,
    PlatformAuthEventType,
    PlatformAuthFailureReason,
    PostStatus,
    RecordStatus,
    Role,
    SkipReason,
    TargetResultStatus,
    TargetType,
    UserStatus,
)

EVENT_SEQ_DEFAULT = text("nextval('global_event_seq')")


def _in(column: str, values: type[StrEnum] | tuple[StrEnum, ...], *, nullable: bool = False) -> str:
    """產生 CHECK 用的「欄位 IN (...)」條件。"""
    listed = ", ".join(f"'{value.value}'" for value in values)
    condition = f"{column} IN ({listed})"
    return f"{column} IS NULL OR {condition}" if nullable else condition


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=clock.now, server_default=func.now(), nullable=False
    )


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        default=clock.now,
        onupdate=clock.now,
        server_default=func.now(),
        nullable=False,
    )


# ---------- 5.1～5.3 帳號（M1） ----------


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint("email = lower(btrim(email))", name="ck_user_account_email_normalized"),
        CheckConstraint(_in("role", Role), name="ck_user_account_role"),
        CheckConstraint(_in("status", UserStatus), name="ck_user_account_status"),
        CheckConstraint("failed_login_count >= 0", name="ck_user_account_failed_login_count"),
    )

    id: Mapped[int] = _pk()
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, default=UserStatus.ACTIVE, server_default=UserStatus.ACTIVE
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class UserSession(Base):
    """登入工作階段：讓伺服器端可以讓單一或全部登入憑證立即失效（BR-43）。"""

    __tablename__ = "user_session"
    __table_args__ = (
        Index(
            "ix_user_session_active_user",
            "user_account_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = _pk()
    user_account_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"))
    refresh_token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSecurityEvent(Base):
    """登入安全事件（只能新增）。"""

    __tablename__ = "login_security_event"
    __table_args__ = (
        CheckConstraint("event_type = 'LOGIN_FAILED'", name="ck_login_security_event_type"),
        CheckConstraint(
            _in("failure_reason", LoginFailureReason), name="ck_login_security_event_reason"
        ),
        CheckConstraint(
            "(failure_reason = 'ACCOUNT_NOT_FOUND') = (user_account_id IS NULL)",
            name="ck_login_security_event_account",
        ),
        Index("ix_login_security_event_occurred", text("occurred_at DESC"), text("event_seq DESC")),
        Index("ix_login_security_event_account", "user_account_id"),
    )

    id: Mapped[int] = _pk()
    event_seq: Mapped[int] = mapped_column(
        BigInteger, unique=True, server_default=EVENT_SEQ_DEFAULT
    )
    event_type: Mapped[str] = mapped_column(
        Text, default="LOGIN_FAILED", server_default="LOGIN_FAILED"
    )
    failure_reason: Mapped[str] = mapped_column(Text)
    attempted_email: Mapped[str] = mapped_column(Text)
    user_account_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    occurred_at: Mapped[datetime] = _created_at()


# ---------- 5.4～5.5 平台帳號（M2） ----------


class PlatformAccount(Base):
    __tablename__ = "platform_account"
    __table_args__ = (
        CheckConstraint(_in("platform", Platform), name="ck_platform_account_platform"),
        CheckConstraint(_in("auth_status", AuthStatus), name="ck_platform_account_auth_status"),
        CheckConstraint(
            "platform <> 'discord' OR auth_expires_at IS NULL",
            name="ck_platform_account_discord_no_expiry",
        ),
        Index(
            "uq_platform_account_name_active",
            "platform",
            "account_name",
            unique=True,
            postgresql_where=text("NOT removed"),
        ),
    )

    id: Mapped[int] = _pk()
    platform: Mapped[str] = mapped_column(Text)
    platform_user_id: Mapped[str | None] = mapped_column(Text)
    account_name: Mapped[str] = mapped_column(Text)
    # 只記錄「平台明確回應失效」；時間到期由 effective_auth_status() 於讀取時計算
    auth_status: Mapped[str] = mapped_column(
        Text, default=AuthStatus.VALID, server_default=AuthStatus.VALID
    )
    auth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # MultiFernet 加密後的 JSON，內容由各平台的 Adapter 定義（foundation-plan D-13）
    credential_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    credential_key_version: Mapped[int] = mapped_column(Integer)
    linked_by: Mapped[int] = mapped_column(ForeignKey("user_account.id"))
    removed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class PlatformAuthEvent(Base):
    """平台授權事件（只能新增）。不得保存任何憑證、Token 或 Webhook 網址。"""

    __tablename__ = "platform_auth_event"
    __table_args__ = (
        CheckConstraint(
            _in("event_type", PlatformAuthEventType), name="ck_platform_auth_event_type"
        ),
        CheckConstraint(_in("platform", Platform), name="ck_platform_auth_event_platform"),
        CheckConstraint(
            _in("failure_reason", PlatformAuthFailureReason), name="ck_platform_auth_event_reason"
        ),
        CheckConstraint(
            "event_type <> 'RELINK_FAILED' OR platform_account_id IS NOT NULL",
            name="ck_platform_auth_event_relink_account",
        ),
        Index("ix_platform_auth_event_occurred", text("occurred_at DESC"), text("event_seq DESC")),
        Index("ix_platform_auth_event_actor", "actor_id"),
    )

    id: Mapped[int] = _pk()
    event_seq: Mapped[int] = mapped_column(
        BigInteger, unique=True, server_default=EVENT_SEQ_DEFAULT
    )
    event_type: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    account_name: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str] = mapped_column(Text)
    platform_account_id: Mapped[int | None] = mapped_column(ForeignKey("platform_account.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"))
    occurred_at: Mapped[datetime] = _created_at()


# ---------- 5.6～5.8 貼文與圖片（M3） ----------


class MediaFile(Base):
    __tablename__ = "media_file"
    __table_args__ = (
        CheckConstraint("format = 'jpeg'", name="ck_media_file_format"),
        CheckConstraint("size_bytes BETWEEN 1 AND 8000000", name="ck_media_file_size"),
        CheckConstraint("width > 0 AND height > 0", name="ck_media_file_dimensions"),
    )

    id: Mapped[int] = _pk()
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    public_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text, default="jpeg", server_default="jpeg")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class MediaBlob(Base):
    """圖片內容（MEDIA_STORAGE_BACKEND=db 時使用）。

    正式環境不另外申請付費的物件儲存，圖片存在資料庫，由後端提供網址。
    """

    __tablename__ = "media_blob"

    storage_key: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created_at()


class Post(Base):
    __tablename__ = "post"
    __table_args__ = (
        CheckConstraint("btrim(content) <> ''", name="ck_post_content_not_blank"),
        CheckConstraint(_in("status", PostStatus), name="ck_post_status"),
        CheckConstraint(
            "status <> 'SCHEDULED' OR scheduled_at IS NOT NULL", name="ck_post_scheduled_has_time"
        ),
        CheckConstraint("status <> 'DRAFT' OR scheduled_at IS NULL", name="ck_post_draft_no_time"),
        Index("ix_post_created", text("created_at DESC"), text("id DESC")),
        Index("ix_post_status_scheduled", "status", "scheduled_at"),
        Index("ix_post_status_publishing", "status", "publishing_started_at"),
    )

    id: Mapped[int] = _pk()
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, default=PostStatus.DRAFT, server_default=PostStatus.DRAFT
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"))
    publishing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    # 軟刪除（foundation-plan D-04）：有值代表已刪除，一般查詢一律排除
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped[UserAccount] = relationship(foreign_keys=[creator_id])
    image: Mapped["PostImage | None"] = relationship(uselist=False, viewonly=True)


class PostImage(Base):
    __tablename__ = "post_image"
    __table_args__ = (
        Index("ix_post_image_original_media", "original_media_id"),
        Index("ix_post_image_ig_media", "ig_media_id"),
    )

    id: Mapped[int] = _pk()
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id", ondelete="CASCADE"), unique=True)
    original_media_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    ig_media_id: Mapped[int] = mapped_column(ForeignKey("media_file.id"))
    created_at: Mapped[datetime] = _created_at()

    original: Mapped[MediaFile] = relationship(foreign_keys=[original_media_id])
    instagram: Mapped[MediaFile] = relationship(foreign_keys=[ig_media_id])

    @property
    def cropped(self) -> bool:
        """Instagram 版本的寬高與原圖不同才算裁切；只是重新編碼（例如 MPO 轉成一般 JPEG）不算。"""
        return (self.instagram.width, self.instagram.height) != (self.original.width, self.original.height)


# ---------- 5.9～5.11 目標與發佈紀錄（M4、M5） ----------


class PostTarget(Base):
    __tablename__ = "post_target"
    __table_args__ = (Index("ix_post_target_platform_account", "platform_account_id"),)

    post_id: Mapped[int] = mapped_column(
        ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("platform_account.id"), primary_key=True
    )
    created_at: Mapped[datetime] = _created_at()


class PublishRecord(Base):
    """一則貼文在一個目標平台帳號上的發佈結果；每個（貼文, 平台帳號）只有一筆。"""

    __tablename__ = "publish_record"
    __table_args__ = (
        UniqueConstraint("post_id", "platform_account_id", name="uq_publish_record_post_account"),
        CheckConstraint(_in("status", RecordStatus), name="ck_publish_record_status"),
        CheckConstraint(
            "status <> 'SUCCEEDED' OR published_at IS NOT NULL",
            name="ck_publish_record_succeeded_has_time",
        ),
        CheckConstraint(
            "status <> 'FAILED' OR failure_reason IS NOT NULL",
            name="ck_publish_record_failed_has_reason",
        ),
        CheckConstraint(
            _in("failure_reason", FailureReason, nullable=True),
            name="ck_publish_record_failure_reason",
        ),
        CheckConstraint(
            _in("image_variant", ImageVariant, nullable=True),
            name="ck_publish_record_image_variant",
        ),
        CheckConstraint("auto_retry_count BETWEEN 0 AND 1", name="ck_publish_record_auto_retry"),
        Index("ix_publish_record_post_status", "post_id", "status"),
        Index("ix_publish_record_status_post", "status", "post_id"),
        Index("ix_publish_record_platform_account", "platform_account_id"),
    )

    id: Mapped[int] = _pk()
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id"))
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_account.id"))
    status: Mapped[str] = mapped_column(
        Text, default=RecordStatus.PENDING, server_default=RecordStatus.PENDING
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_post_url: Mapped[str | None] = mapped_column(Text)
    platform_post_id: Mapped[str | None] = mapped_column(Text)
    # 平台中途識別碼（例如 container ID）：begin 之後立刻保存，供接續與逾時恢復使用（D-01）
    platform_request_ref: Mapped[str | None] = mapped_column(Text)
    # 「這一次嘗試」開始的時間；距今未超過單筆總時限時，其他執行者不可接手（D-01、D-02）
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_summary: Mapped[str | None] = mapped_column(Text)
    image_sha256: Mapped[str | None] = mapped_column(Text)
    image_format: Mapped[str | None] = mapped_column(Text)
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    image_variant: Mapped[str | None] = mapped_column(Text)
    auto_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    # 只有管理員可看；寫入前必須過濾憑證
    platform_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    platform_account: Mapped[PlatformAccount] = relationship()


class PublishRecordHistory(Base):
    """發佈紀錄變更歷程（只能新增）：建立與每次狀態實際改變各一筆。"""

    __tablename__ = "publish_record_history"
    __table_args__ = (
        CheckConstraint(
            "from_status IS DISTINCT FROM to_status", name="ck_publish_record_history_changed"
        ),
        CheckConstraint(_in("actor_type", ActorType), name="ck_publish_record_history_actor_type"),
        CheckConstraint(
            "(actor_type = 'system') = (actor_id IS NULL)",
            name="ck_publish_record_history_actor",
        ),
        CheckConstraint(_in("reason", HistoryReason), name="ck_publish_record_history_reason"),
        Index("ix_publish_record_history_record", "publish_record_id", "changed_at"),
    )

    id: Mapped[int] = _pk()
    publish_record_id: Mapped[int] = mapped_column(ForeignKey("publish_record.id"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = _created_at()
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    reason: Mapped[str] = mapped_column(Text)


# ---------- 5.12～5.13 稽核（共用核心） ----------


class AuditLog(Base):
    """稽核紀錄（只能新增）。只能經由 core.audit.write() 寫入。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(_in("actor_type", ActorType), name="ck_audit_log_actor_type"),
        CheckConstraint("(actor_type = 'system') = (actor_id IS NULL)", name="ck_audit_log_actor"),
        CheckConstraint(_in("action", AuditAction), name="ck_audit_log_action"),
        CheckConstraint(_in("target_type", TargetType), name="ck_audit_log_target_type"),
        CheckConstraint(
            _in("result", FINAL_POST_STATUSES, nullable=True), name="ck_audit_log_result"
        ),
        Index("ix_audit_log_occurred", text("occurred_at DESC"), text("event_seq DESC")),
        Index("ix_audit_log_actor", "actor_id"),
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_action", "action"),
    )

    id: Mapped[int] = _pk()
    event_seq: Mapped[int] = mapped_column(
        BigInteger, unique=True, server_default=EVENT_SEQ_DEFAULT
    )
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    # 多型參照（帳號、平台帳號或貼文），不加外鍵
    target_id: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = _created_at()
    reason: Mapped[str | None] = mapped_column(Text)
    related_post_id: Mapped[int | None] = mapped_column(BigInteger)
    scheduled_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    post_creator_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    result: Mapped[str | None] = mapped_column(Text)

    target_results: Mapped[list["AuditTargetResult"]] = relationship(
        back_populates="audit_log", order_by="AuditTargetResult.id"
    )


class AuditTargetResult(Base):
    """稽核紀錄中各目標平台帳號的執行結果（只能新增）。"""

    __tablename__ = "audit_target_result"
    __table_args__ = (
        CheckConstraint(_in("status", TargetResultStatus), name="ck_audit_target_result_status"),
        CheckConstraint(
            "status <> 'FAILED' OR failure_reason IS NOT NULL",
            name="ck_audit_target_result_failed_has_reason",
        ),
        CheckConstraint(
            "(status = 'NOT_RETRIED') = (skip_reason IS NOT NULL)",
            name="ck_audit_target_result_skip",
        ),
        CheckConstraint(
            _in("skip_reason", SkipReason, nullable=True), name="ck_audit_target_result_skip_reason"
        ),
        Index("ix_audit_target_result_audit_log", "audit_log_id"),
        Index("ix_audit_target_result_platform_account", "platform_account_id"),
    )

    id: Mapped[int] = _pk()
    audit_log_id: Mapped[int] = mapped_column(ForeignKey("audit_log.id"))
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_account.id"))
    status: Mapped[str] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    skip_reason: Mapped[str | None] = mapped_column(Text)

    audit_log: Mapped[AuditLog] = relationship(back_populates="target_results")


# 只能新增的表（NFR-08）：migration 為這些表掛上禁止 UPDATE／DELETE／TRUNCATE 的觸發器
APPEND_ONLY_TABLES = (
    "audit_log",
    "audit_target_result",
    "login_security_event",
    "platform_auth_event",
    "publish_record_history",
)
