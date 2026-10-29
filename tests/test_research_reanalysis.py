"""Offline regression tests; no fixtures from the private vault."""
import importlib.util
from pathlib import Path

P = Path(__file__).resolve().parents[1] / 'scripts/research_reanalysis.py'

def module():
    spec = importlib.util.spec_from_file_location('research_reanalysis', P)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_abstention_exact_and_mixed_are_distinct():
    m = module()
    assert m.classify_abstention('Não encontrei essa informação no contexto.') == 'bare'
    assert m.classify_abstention('  “Não encontrei essa informação no contexto.” ') == 'bare'
    assert m.classify_abstention('Não encontrei essa informação no contexto. Mas o valor é 42.') == 'mixed_prefix'
    assert m.classify_abstention('O valor é 42. Não encontrei outro dado.') == 'other'

def test_rule_does_not_penalize_appropriate_abstention():
    m = module()
    text = 'Não encontrei essa informação no contexto.'
    assert m.corrected_verdict('CORRECT', text, True, 'strict') == 'ABSTAIN'
    assert m.corrected_verdict('ABSTAIN', text, False, 'strict') == 'ABSTAIN'
    assert m.corrected_verdict('CORRECT', text, False, 'strict') == 'CORRECT'
    mixed = text + ' Há uma hipótese adicional.'
    assert m.corrected_verdict('CORRECT', mixed, True, 'strict') == 'CORRECT'
    assert m.corrected_verdict('CORRECT', mixed, True, 'r1') == 'ABSTAIN'

def test_index_preserves_duplicate_evidence_and_last_write_policy():
    m = module()
    rows = [(1, {'model':'m','arm':'a','qid':'q','rep':1,'verdict':'ABSTAIN'}),
            (2, {'model':'m','arm':'a','qid':'q','rep':1,'verdict':'CORRECT'})]
    index, duplicates = m.index_rows(rows)
    assert index[('m','a','q',1)][0] == 2
    assert len(duplicates) == 1
    assert duplicates[0]['lines'] == [1,2]
    assert duplicates[0]['conflicting_verdicts']

def test_pair_counts_require_both_sides_and_use_correct_order():
    m = module()
    assert m.pair_category(True, False) == 'off_only'
    assert m.pair_category(False, True) == 'on_only'
    assert m.pair_category(True, True) == 'both_correct'
    assert m.pair_category(False, False) == 'neither_correct'
    assert m.pair_category(None, True) == 'missing'

def test_metadata_does_not_execute_or_evaluate_private_gold_paths(tmp_path):
    p = tmp_path / 'definitions.py'
    p.write_text("N = 'private/'\nQ = [('numeric', 'question', [N+'secret.md'], r'42')]\nraise RuntimeError('must never execute')\n", encoding='utf-8')
    assert module().question_metadata(p) == {'d2q001': {'classe':'numeric', 'answer_regex':'42'}}

def test_cluster_interval_deterministic_and_question_level():
    m = module()
    x = {'q1':[1,1], 'q2':[-1,-1]}
    a = m.cluster_interval(x, repetitions=100, seed=42)
    assert a == m.cluster_interval(x, repetitions=100, seed=42)
    assert a['questions'] == 2 and a['pairs'] == 4 and a['difference'] == 0
