"""Check the two built editions and the integrity of their shared results."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

import fitz

ROOT = Path(__file__).resolve().parent


def check() -> dict:
    report = {}
    english = (ROOT / 'Anamnesia_Research_Paper.tex').read_text(encoding='utf-8')
    portuguese = (ROOT / 'Anamnesia_Research_Paper_PT.tex').read_text(encoding='utf-8')
    for command in ('label', 'cite', 'ref', 'eqref'):
        pattern = r'\\' + command + r'\{([^}]+)\}'
        assert Counter(re.findall(pattern, english)) == Counter(re.findall(pattern, portuguese)), command
    tables = [(ROOT / name).read_text(encoding='utf-8') for name in ('tables.tex', 'tables_PT.tex')]
    # Compare numeric table cells only: translated captions and headers may differ.
    numeric_cells = []
    for table in tables:
        cells = []
        for line in table.splitlines():
            if '&' not in line or '\\toprule' in line or '\\multicolumn' in line:
                continue
            for cell in line.split('&')[1:]:
                cells.extend(re.findall(r'\d+(?:\.\d+)?', cell))
        numeric_cells.append(cells)
    assert numeric_cells[0] == numeric_cells[1], 'Numeric table results differ between editions'
    expected_figures = re.findall(r'\\paperfigure(?:\[[^]]+\])?\{([^}]+)\}', english)
    assert len(expected_figures) == 16
    for lang, source, folder in [('en', english, 'figures'), ('pt-BR', portuguese, 'figures_pt')]:
        assert re.findall(r'\\paperfigure(?:\[[^]]+\])?\{([^}]+)\}', source) == expected_figures
        assert all((ROOT / folder / name).is_file() for name in expected_figures)
        pdf_name = 'Anamnesia_Research_Paper' + ('_PT' if lang == 'pt-BR' else '') + '.pdf'
        doc = fitz.open(ROOT / pdf_name)
        out_of_page = []
        for pnum, page in enumerate(doc, 1):
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        box = fitz.Rect(span['bbox'])
                        if not (page.rect + (-1, -1, 1, 1)).contains(box):
                            out_of_page.append({'page': pnum, 'text': span['text'], 'bbox': list(box)})
        assert not out_of_page, out_of_page
        text = '\n'.join(page.get_text() for page in doc)
        assert 'v2.1.0' in text
        assert len(text) > 30000, 'Unexpectedly incomplete paper'
        report[lang] = {'pdf': pdf_name, 'pages': len(doc), 'figures': len(expected_figures), 'out_of_page_spans': len(out_of_page), 'text_characters': len(text)}
    report['checks'] = ['matching labels/citations/references', 'matching numeric table cells', '16 figure sources per language', 'nonempty complete PDFs', 'no out-of-page text spans']
    return report


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False, indent=2))
