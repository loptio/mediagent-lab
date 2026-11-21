"""API 測試共用的小工具。"""

from sqlalchemy import select

from app.core import models
from app.core.enums import Platform, Role
from tests.factories import DEFAULT_PASSWORD, make_account, make_user

API = "/api/v1"


def login(client, email, password=DEFAULT_PASSWORD):
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_club(db):
    """三種角色各一位，Threads、Instagram、Discord 各一個已連結的平台帳號。"""
    users = {
        "admin": make_user(db, "president@club.tw", Role.ADMIN, "社長"),
        "publisher": make_user(db, "pr@club.tw", Role.PUBLISHER, "公關"),
        "writer": make_user(db, "newbie@club.tw", Role.WRITER, "新進幹部"),
    }
    accounts = {
        "threads": make_account(db, users["admin"], Platform.THREADS, "ntu_guitar_threads"),
        "instagram": make_account(db, users["admin"], Platform.INSTAGRAM, "ntu_guitar_ig"),
        "discord": make_account(db, users["admin"], Platform.DISCORD, "公告"),
    }
    db.commit()
    return users, accounts


def create_post_with_targets(client, headers, account_ids, content="本週三 19:00 社課"):
    created = client.post(f"{API}/posts", json={"content": content}, headers=headers)
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    targets = client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": account_ids},
        headers=headers,
    )
    assert targets.status_code == 200, targets.text
    return post_id


def publish(client, headers, post_id):
    return client.post(
        f"{API}/posts/{post_id}/publish-jobs", json={"type": "immediate"}, headers=headers
    )


def records_by_account(client, headers, post_id):
    body = client.get(f"{API}/posts/{post_id}/publish-records", headers=headers).json()
    return {item["platform_account"]["account_name"]: item for item in body["items"]}


def history_rows(db, post_id):
    rows = db.execute(
        select(models.PublishRecordHistory, models.PublishRecord)
        .join(models.PublishRecord)
        .where(models.PublishRecord.post_id == post_id)
        .order_by(models.PublishRecordHistory.id)
    )
    return [(h.from_status, h.to_status, h.actor_type, h.reason) for h, _ in rows]
