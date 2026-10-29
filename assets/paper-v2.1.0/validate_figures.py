"""Validate all 16 bilingual figures after running both generators."""
import collections
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    'fig_headline','fig_cost_by_model','fig_saving_heatmap','fig_accuracy_by_model',
    'fig_pareto','fig_by_class','fig_retrieval','fig_retrieval_latency',
    'diag_architecture','diag_query_flow','diag_optimization_layer','diag_graphify_jev',
    'diag_persistence_cycle','diag_agent_mcp_gateway','diag_with_vs_without','diag_cost_accounting',
}

def svg_text(path):
    return [''.join(t.itertext()) for t in ET.parse(path).getroot().iter('{http://www.w3.org/2000/svg}text')]


def main():
    failures = []
    for directory in ('figures','figures_pt'):
        folder = ROOT/directory
        for extension in ('png','pdf','svg','layout.json'):
            actual = {p.name.removesuffix('.'+extension) for p in folder.glob('*.'+extension)}
            if actual != EXPECTED:
                failures.append(f'{directory}/{extension}: missing={EXPECTED-actual}; extra={actual-EXPECTED}')
        for name in sorted(EXPECTED):
            path = folder/f'{name}.layout.json'
            if not path.exists(): continue
            report = json.loads(path.read_text(encoding='utf-8'))
            if report['text_overlaps'] or report['box_overflows'] or report['clipped_boxes']:
                failures.append(f'{directory}/{name}: {report}')
            for extension in ('png','pdf','svg'):
                artifact = folder/f'{name}.{extension}'
                if not artifact.exists() or artifact.stat().st_size < 500:
                    failures.append(f'Missing/empty artifact: {artifact}')
    for name in sorted(EXPECTED):
        en,pt = [svg_text(ROOT/d/f'{name}.svg') for d in ('figures','figures_pt')]
        # Compare displayed numbers, including labels, formulae and all data values.
        numbers = lambda texts: collections.Counter(re.findall(r'\d+(?:[.,]\d+)*', '\n'.join(texts)))
        if numbers(en) != numbers(pt):
            failures.append(f'{name}: EN/PT displayed numbers differ: {numbers(en)-numbers(pt)}, {numbers(pt)-numbers(en)}')
        leftovers = {'Without','Auto+Opt.','accuracy (%)','cold','hot (cache)','Agent','Question',
                     'Injection flag','Adaptive cut','Demotion','Cost','Generation','State'}
        leaked = leftovers.intersection(pt)
        if leaked:
            failures.append(f'{name}: untranslated text: {sorted(leaked)}')
    if failures:
        raise SystemExit('\n'.join(failures))
    print('PASS: 16 figures x 2 languages x 3 formats; 32 clean layout reports; identical EN/PT displayed numbers; translation smoke checks.')
    print('Scope: rendered text bounds and box containment, not a proof of arrow/curve clearance. PNGs must also be visually inspected.')

if __name__ == '__main__':
    main()
