"""驗收：查詢貼文列表（spec/features/查詢貼文列表.feature）。"""

from datetime import timedelta  # noqa: F401

from pytest_bdd import given, scenarios, then, when  # noqa: F401
from sqlalchemy import select  # noqa: F401

from app.core import clock, models  # noqa: F401
from tests.bdd import labels as L  # noqa: F401
from tests.bdd.conftest import feature
from tests.bdd.labels import code, tw_time  # noqa: F401
from tests.bdd.steps.common import Result, iso, rows, step  # noqa: F401

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {}

scenarios(feature("查詢貼文列表"))


@given(step('系統中另有 (?P<n>\\d+) 則由 "X" 建立的草稿貼文'))
def given_many_drafts(world, n, a):
    for index in range(int(n)):
        post = models.Post(content=f"草稿 {index + 1}", creator_id=world.user_id(a))
        post.created_at = clock.now() - timedelta(days=30, minutes=index)
        world.db.add(post)
    world.db.commit()


@when(step('"X" 查詢狀態為 "X" 的貼文列表'))
def when_list_by_status(world, a, b):
    world.request(a, "GET", "/posts", params={"status": code(L.POST_STATUS, b)})


@when(step('"X" 查詢貼文列表，第 (?P<page>\\d+) 頁，每頁 (?P<size>\\d+) 筆'))
def when_list_page(world, a, page, size):
    world.request(a, "GET", "/posts", params={"page": page, "page_size": size})
