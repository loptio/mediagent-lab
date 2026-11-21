import pytest

from app.core.enums import PostStatus as S
from app.core.errors import DomainError
from app.core.posts import transition_post
from tests.factories import make_post, make_user


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (S.DRAFT, S.SCHEDULED), (S.SCHEDULED, S.DRAFT), (S.DRAFT, S.PUBLISHING),
        (S.SCHEDULED, S.PUBLISHING), (S.PUBLISHING, S.PUBLISHED),
        (S.PUBLISHING, S.PARTIALLY_FAILED), (S.PUBLISHING, S.FAILED),
        (S.PARTIALLY_FAILED, S.PUBLISHING), (S.FAILED, S.PUBLISHING),
    ],
)
def test_transition_allows_br12_paths(db, start, end):
    post = make_post(db, make_user(db))
    post.status = start

    transition_post(post, end)

    assert post.status == end


@pytest.mark.parametrize(
    ("start", "end"),
    [(S.DRAFT, S.PUBLISHED), (S.PUBLISHED, S.PUBLISHING), (S.PUBLISHING, S.DRAFT)],
)
def test_transition_rejects_draft_to_published(db, start, end):
    post = make_post(db, make_user(db))
    post.status = start

    with pytest.raises(DomainError) as error:
        transition_post(post, end)
    assert error.value.status_code == 409
    assert post.status == start
