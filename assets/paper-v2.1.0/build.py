"""Build both language editions with Tectonic; never calls model APIs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tectonic', default=os.environ.get('TECTONIC', 'tectonic'))
    parser.add_argument('--regenerate-figures', action='store_true', help='Requires matplotlib and numpy')
    args = parser.parse_args()
    engine = shutil.which(args.tectonic)
    if engine is None:
        raise SystemExit('Tectonic not found. Install it or pass --tectonic PATH.')
    if args.regenerate_figures:
        import sys
        for language in ('en', 'pt'):
            for script in ('make_paper_figs.py', 'make_diagrams.py'):
                subprocess.run([sys.executable, script, '--lang', language], cwd=ROOT, check=True)
        subprocess.run([sys.executable, 'validate_figures.py'], cwd=ROOT, check=True)
    for source in ('Anamnesia_Research_Paper.tex', 'Anamnesia_Research_Paper_PT.tex'):
        subprocess.run([engine, '--keep-logs', source], cwd=ROOT, check=True)
        pdf = ROOT / Path(source).with_suffix('.pdf')
        if not pdf.is_file() or pdf.stat().st_size == 0:
            raise SystemExit(f'Missing or empty output: {pdf.name}')
        print(f'Built {pdf.name} ({pdf.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
