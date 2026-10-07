import json
import sys
from pathlib import Path

from app.routing.verifiers import (
    VerifyLevel, normalize, run_level, verify_abstention, verify_citation, verify_fact_match,
    verify_grounding, verify_json_schema, verify_tests_pass,
)

SNIP = ["O timeout de 157ms foi definido no OzmarelleProxy antes do fallback textual."]


def test_grounding_pass_and_fail():
    assert verify_grounding("Timeout de 157 ms definido no OzmarelleProxy.", SNIP).passed
    r = verify_grounding("Banana cavalo montanha violeta orquestra.", SNIP)
    assert not r.passed and r.failure_code == "ungrounded_sentence"


def test_grounding_threshold_configurable_and_edges():
    ans = "Timeout definido no OzmarelleProxy com garantia contratual extra."
    assert not verify_grounding(ans, SNIP, threshold=0.9).passed
    assert verify_grounding(ans, SNIP, threshold=0.4).passed
    assert verify_grounding("", SNIP).failure_code == "empty_answer"
    assert verify_grounding("algo", []).failure_code == "no_snippets"


def test_citation():
    assert verify_citation(["a.md"], ["a.md", "b.md"]).passed
    r = verify_citation(["z.md"], ["a.md"])
    assert not r.passed and r.details["missing"] == ["z.md"]
    assert verify_citation([], ["a.md"]).failure_code == "no_citation"
    assert verify_citation([], ["a.md"], require_at_least_one=False).passed


def test_fact_match_accent_case_number_normalization():
    assert verify_fact_match("O TIMEOUT foi de 157 ms.", ["157ms"]).passed
    assert verify_fact_match("versão 1,5 do módulo", ["versao 1.5"]).passed
    assert verify_fact_match("KrampusDB v7.111-rc0 validado.", ["krampusdb v7.111-rc0"]).passed
    assert normalize("Ação") == "acao"
    r = verify_fact_match("nada", ["157ms", "x"])
    assert not r.passed and r.failure_code == "fact_missing"
    assert verify_fact_match("157ms", ["157ms", "x"], mode="any").passed
    assert verify_fact_match("x", []).failure_code == "no_expected_facts"


def test_fact_match_does_not_confuse_numbers():
    assert not verify_fact_match("timeout de 158ms", ["157ms"]).passed


def test_abstention():
    assert verify_abstention("Não existe nota sobre isso.").passed
    assert verify_abstention("A decisão foi usar X.").failure_code == "hallucinated_answer"


SCHEMA = {"type": "object", "required": ["a", "k"],
          "properties": {"a": {"type": "integer"}, "k": {"type": "string", "enum": ["x", "y"]},
                         "l": {"type": "array", "items": {"type": "string"}}}}


def test_json_schema():
    assert verify_json_schema({"a": 1, "k": "x"}, SCHEMA).passed
    assert verify_json_schema('{"a": 1, "k": "y", "l": ["q"]}', SCHEMA).passed
    assert verify_json_schema("{bad", SCHEMA).failure_code == "invalid_json"
    assert not verify_json_schema({"a": 1}, SCHEMA).passed
    assert not verify_json_schema({"a": "1", "k": "x"}, SCHEMA).passed
    assert not verify_json_schema({"a": True, "k": "x"}, SCHEMA).passed
    assert not verify_json_schema({"a": 1, "k": "z"}, SCHEMA).passed
    assert not verify_json_schema({"a": 1, "k": "x", "l": [3]}, SCHEMA).passed


def test_tests_pass_wrapper(tmp_path):
    assert verify_tests_pass(["x"], str(tmp_path)).failure_code == "not_run"  # disabled by default
    (tmp_path / "ok.py").write_text("import sys; sys.exit(0)")
    (tmp_path / "bad.py").write_text("import sys; sys.exit(3)")
    (tmp_path / "slow.py").write_text("import time; time.sleep(10)")
    assert verify_tests_pass([sys.executable, "ok.py"], str(tmp_path), enabled=True).passed
    r = verify_tests_pass([sys.executable, "bad.py"], str(tmp_path), enabled=True)
    assert not r.passed and r.failure_code == "tests_failed"
    assert verify_tests_pass([sys.executable, "slow.py"], str(tmp_path), timeout_s=0.5, enabled=True).failure_code == "timeout"
    assert verify_tests_pass(["x"], str(tmp_path / "nope"), enabled=True).failure_code == "bad_config"
    # runs in a copy: files written by the command don't leak into the original
    (tmp_path / "w.py").write_text("open('leak.txt','w').write('1')")
    verify_tests_pass([sys.executable, "w.py"], str(tmp_path), enabled=True)
    assert not (tmp_path / "leak.txt").exists()


def test_levels():
    ok = verify_fact_match("157ms", ["157ms"])
    bad = verify_fact_match("x", ["157ms"])
    assert run_level("NONE", [ok]).passed is None
    assert run_level("LIGHT", [ok]).passed is True
    assert run_level("LIGHT", [ok, bad]).passed is False
    full = run_level(VerifyLevel.FULL, [ok])
    assert full.passed is True and full.details["judge"] == "not_run"
    assert run_level("LIGHT", []).passed is None
