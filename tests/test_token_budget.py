import pytest

from app.gateway.token_budget import estimate_tokens, fit_within, pack_batches, truncate_to_tokens


def test_estimate_tokens_empty_zero_and_nonzero():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("ação") >= 1


def test_estimate_tokens_monotonic():
    text = "palavra " * 200
    prev = 0
    for n in range(1, len(text), 37):
        cur = estimate_tokens(text[:n])
        assert cur >= prev
        prev = cur


_LONG = "\n".join(f"linha número {i} com algumas palavras de conteúdo" for i in range(200))


@pytest.mark.parametrize("limit", [5, 20, 100, 300])
def test_truncate_to_tokens_respects_limit(limit):
    out = truncate_to_tokens(_LONG, limit)
    assert estimate_tokens(out) <= limit
    assert len(out) < len(_LONG)


def test_truncate_short_text_unchanged():
    assert truncate_to_tokens("curto", 100) == "curto"


def test_pack_batches_never_exceeds_budget():
    items = [3, 5, 7, 2, 9, 4, 1, 6, 8]
    budget, base = 15, 2
    batches = pack_batches(items, lambda x: x, budget, base_cost=base)
    assert [x for b in batches for x in b] == items
    for b in batches:
        assert base + sum(b) <= budget


def test_pack_batches_single_oversize_item_own_batch():
    batches = pack_batches([2, 50, 3], lambda x: x, 10)
    assert batches == [[2], [50], [3]]
    for b in batches:
        if sum(b) > 10:
            assert len(b) == 1


def test_pack_batches_empty():
    assert pack_batches([], lambda x: x, 10) == []


def test_fit_within_skips_large_takes_later_small():
    sel, used = fit_within([4, 10, 3, 2], lambda x: x, 9)
    assert sel == [4, 3, 2]
    assert used == 9
    sel, used = fit_within([20], lambda x: x, 5)
    assert sel == [] and used == 0
