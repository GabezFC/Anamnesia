from app.gateway.token_budget import estimate_tokens
from app.schemas.models import Candidate
from app.services.dedup import clean_snippet, content_hash, deduplicate, preprocess


def C(cid, src, sec, snip, score=1.0):
    return Candidate(candidate_id=cid, source_file=src, section=sec, snippet=snip, score=score)


def test_identical_text_different_whitespace_case_one_kept():
    a = C("a", "x.md", "S1", "Python  e FastAPI\n no backend", 2.0)
    b = C("b", "y.md", "S2", "python e fastapi no   BACKEND", 1.0)
    assert content_hash(a.snippet) == content_hash(b.snippet)
    kept, removed = deduplicate([a, b], max_per_note=5)
    assert [c.candidate_id for c in kept] == ["a"]
    assert removed == 1


def test_same_source_section_snippet_dedup():
    a = C("a", "x.md", "S", "mesmo texto", 1.0)
    b = C("b", "x.md", "S", "mesmo texto", 0.5)
    kept, removed = deduplicate([a, b], max_per_note=5)
    assert len(kept) == 1 and removed == 1


def test_max_per_note_keeps_best_score():
    cands = [C("low", "x.md", "A", "texto um", 0.2), C("high", "x.md", "B", "texto dois", 0.9),
             C("mid", "x.md", "C", "texto tres", 0.5), C("other", "y.md", "A", "texto quatro", 0.1)]
    kept, removed = deduplicate(cands, max_per_note=1)
    ids = [c.candidate_id for c in kept]
    assert ids == ["high", "other"]
    assert removed == 2
    kept2, _ = deduplicate(cands, max_per_note=2)
    assert [c.candidate_id for c in kept2 if c.source_file == "x.md"] == ["high", "mid"]


def test_preprocess_drops_empty_and_caps_tokens():
    long = " ".join(f"palavra{i}" for i in range(2000))
    cands = [C("e", "x.md", "S", "   \n\n  "), C("h", "x.md", "S", "## -"), C("l", "y.md", "S", long)]
    out = preprocess(cands, snippet_max_tokens=50)
    assert [c.candidate_id for c in out] == ["l"]
    c = out[0]
    assert estimate_tokens(c.snippet) <= 50
    assert c.token_estimate == estimate_tokens(c.snippet)
    assert c.content_hash == content_hash(c.snippet)


def test_clean_snippet_preserves_code_blocks():
    text = "Texto   com    espaços\n\n\n\n```python\ndef f():\n    x  =  1   \n    return x\n```\nfim"
    out = clean_snippet(text)
    assert "Texto com espaços" in out
    assert "    x  =  1" in out  # inner indentation/spacing kept inside fence
    assert "```python" in out and out.count("```") == 2
    assert "\n\n\n" not in out
