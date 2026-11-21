"""稽核查詢（FR-19、BR-44、BR-45、《API 設計》34）：一般稽核、登入安全事件、平台授權事件合在一起查詢。

三種紀錄共用全域事件序號；依事件時間、再依事件序號由新到舊排列，在資料庫裡合併、排序、分頁。
"""

from datetime import UTC, datetime

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.core.enums import ActorType, AuditAction, PlatformAuthEventType, TargetType
from app.core.errors import DomainError
from app.core.models import AuditLog, LoginSecurityEvent, PlatformAuthEvent, UserAccount
from app.m4_scheduling.service import TAIPEI

from .schemas import AuditItem, EventPage, LoginSecurityItem, Person, PlatformAuthItem, Target, TargetResult

PAGE_SIZES = (20, 50, 100)
LOGIN_FAILED = "LOGIN_FAILED"
AUTH_EVENT_TYPES = {t.value for t in PlatformAuthEventType}
AUDIT_ACTIONS = {a.value for a in AuditAction}
DETAIL_FIELDS = ("reason", "related_post_id", "scheduled_by", "post_creator_id", "result")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=TAIPEI)).astimezone(UTC)


def search(
    db: Session,
    *,
    actor_type: str | None,
    actor_id: int | None,
    account_id: int | None,
    action: str | None,
    start: datetime | None,
    end: datetime | None,
    page: int,
    page_size: int,
) -> EventPage:
    if page < 1 or page_size not in PAGE_SIZES:
        raise DomainError(400, "VALIDATION_ERROR", "page 必須大於 0，page_size 只能是 20、50、100")
    if action is not None and action not in AUDIT_ACTIONS | AUTH_EVENT_TYPES | {LOGIN_FAILED}:
        raise DomainError(400, "VALIDATION_ERROR", "action 不是有效的操作類型")
    start, end = _utc(start), _utc(end)
    by_actor = actor_type is not None or actor_id is not None

    parts = []
    # 一般稽核紀錄
    if action is None or action in AUDIT_ACTIONS:
        stmt = select(literal("audit").label("kind"), AuditLog.id, AuditLog.event_seq, AuditLog.occurred_at)
        if actor_type is not None:
            stmt = stmt.where(AuditLog.actor_type == actor_type)
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if account_id is not None:
            stmt = stmt.where(
                AuditLog.target_type == TargetType.USER_ACCOUNT, AuditLog.target_id == account_id
            )
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        parts.append(_in_range(stmt, AuditLog.occurred_at, start, end))
    # 登入安全事件：依操作者篩選時不列出（BR-45）
    if not by_actor and (action is None or action == LOGIN_FAILED):
        stmt = select(
            literal("login_security").label("kind"),
            LoginSecurityEvent.id,
            LoginSecurityEvent.event_seq,
            LoginSecurityEvent.occurred_at,
        )
        if account_id is not None:
            stmt = stmt.where(LoginSecurityEvent.user_account_id == account_id)
        parts.append(_in_range(stmt, LoginSecurityEvent.occurred_at, start, end))
    # 平台授權事件：操作者一定是使用者；依對應帳號篩選時不列出
    if (
        account_id is None
        and actor_type != ActorType.SYSTEM
        and (action is None or action in AUTH_EVENT_TYPES)
    ):
        stmt = select(
            literal("platform_auth").label("kind"),
            PlatformAuthEvent.id,
            PlatformAuthEvent.event_seq,
            PlatformAuthEvent.occurred_at,
        )
        if actor_id is not None:
            stmt = stmt.where(PlatformAuthEvent.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(PlatformAuthEvent.event_type == action)
        parts.append(_in_range(stmt, PlatformAuthEvent.occurred_at, start, end))

    if not parts:
        return EventPage(
            items=[],
            page=page,
            page_size=page_size,
            total=0,
            total_pages=0,
            has_prev=page > 1,
            has_next=False,
        )
    merged = union_all(*parts).subquery()
    total = db.scalar(select(func.count()).select_from(merged)) or 0
    rows = db.execute(
        select(merged.c.kind, merged.c.id)
        .order_by(merged.c.occurred_at.desc(), merged.c.event_seq.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    total_pages = (total + page_size - 1) // page_size
    return EventPage(
        items=_load(db, rows),
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


def _in_range(stmt, column, start: datetime | None, end: datetime | None):
    """含開始時間、不含結束時間。"""
    if start is not None:
        stmt = stmt.where(column >= start)
    if end is not None:
        stmt = stmt.where(column < end)
    return stmt


def _person(user: UserAccount | None) -> Person | None:
    return Person(id=user.id, email=user.email, name=user.name) if user else None


def _load(db: Session, rows) -> list:
    ids: dict[str, list[int]] = {"audit": [], "login_security": [], "platform_auth": []}
    for kind, row_id in rows:
        ids[kind].append(row_id)
    audits = {
        a.id: a
        for a in db.scalars(
            select(AuditLog)
            .options(selectinload(AuditLog.target_results))
            .where(AuditLog.id.in_(ids["audit"]))
        )
    }
    logins = {
        e.id: e
        for e in db.scalars(
            select(LoginSecurityEvent).where(LoginSecurityEvent.id.in_(ids["login_security"]))
        )
    }
    auths = {
        e.id: e
        for e in db.scalars(select(PlatformAuthEvent).where(PlatformAuthEvent.id.in_(ids["platform_auth"])))
    }
    user_ids = (
        {a.actor_id for a in audits.values()}
        | {e.user_account_id for e in logins.values()}
        | {e.actor_id for e in auths.values()}
    )
    users = {u.id: u for u in db.scalars(select(UserAccount).where(UserAccount.id.in_(user_ids - {None})))}

    items = []
    for kind, row_id in rows:
        if kind == "audit":
            a = audits[row_id]
            items.append(
                AuditItem(
                    id=a.id,
                    event_seq=a.event_seq,
                    occurred_at=a.occurred_at,
                    actor_type=a.actor_type,
                    actor=_person(users.get(a.actor_id)),
                    action=a.action,
                    target=Target(type=a.target_type, id=a.target_id),
                    details={f: getattr(a, f) for f in DETAIL_FIELDS if getattr(a, f) is not None},
                    target_results=[
                        TargetResult(
                            platform_account_id=r.platform_account_id,
                            status=r.status,
                            failure_reason=r.failure_reason,
                            skip_reason=r.skip_reason,
                        )
                        for r in a.target_results
                    ],
                )
            )
        elif kind == "login_security":
            e = logins[row_id]
            items.append(
                LoginSecurityItem(
                    id=e.id,
                    event_seq=e.event_seq,
                    occurred_at=e.occurred_at,
                    event_type=e.event_type,
                    failure_reason=e.failure_reason,
                    attempted_email=e.attempted_email,
                    account=_person(users.get(e.user_account_id)),
                )
            )
        else:
            e = auths[row_id]
            items.append(
                PlatformAuthItem(
                    id=e.id,
                    event_seq=e.event_seq,
                    occurred_at=e.occurred_at,
                    actor=_person(users[e.actor_id]),
                    event_type=e.event_type,
                    platform=e.platform,
                    account_name=e.account_name,
                    platform_account_id=e.platform_account_id,
                    failure_reason=e.failure_reason,
                )
            )
    return items
