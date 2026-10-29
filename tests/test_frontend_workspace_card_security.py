"""Production-function regression for raw status metadata vs escaped live fallback."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node not installed')
@pytest.mark.parametrize('from_api', [True, False])
@pytest.mark.parametrize('value', ['<img src=x onerror=synthetic>', 'synthetic" data-injected="yes & <tag>'])
def test_workspace_project_card_escapes_status_once(from_api, value):
    assert NODE is not None
    code = r'''
    import fs from 'node:fs';
    const input = JSON.parse(process.argv[1]);
    const source = fs.readFileSync(input.workspace, 'utf8');
    const format = fs.readFileSync(input.format, 'utf8');
    const escSrc = format.slice(format.indexOf('export const esc ='), format.indexOf('/** Safe nested get.'));
    const esc = new Function(escSrc.replace('export ', '') + ';return esc;')();
    const card = source.slice(source.indexOf('function wioProjectCard('), source.indexOf('/** Painel de progresso/resultado'));
    const project = {name: input.value, path: input.value};
    const fallback = {name: esc(input.value), path: esc(input.value)};
    const wio = {status: {loading: false, error: null, apiMissing: false,
      data: input.from_api ? {project, availability: {available: true}, index: {}} : null}};
    const html = new Function('wio', 'wioProject', 'esc', card + ';return wioProjectCard({});')(wio, () => fallback, esc);
    console.log(JSON.stringify({html, escaped: esc(input.value)}));
    '''
    payload = {'workspace': str(ROOT/'frontend/js/pages/workspace.js'),
               'format': str(ROOT/'frontend/js/format.js'), 'value': value, 'from_api': from_api}
    result = subprocess.run([NODE, '--input-type=module', '-e', code, json.dumps(payload)],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    html, escaped = output['html'], output['escaped']
    assert f'<div class="wio-project-name">{escaped}</div>' in html
    assert f'<div class="wio-project-path" title="{escaped}">{escaped}</div>' in html
    assert '<img' not in html
    assert ' data-injected="yes' not in html
