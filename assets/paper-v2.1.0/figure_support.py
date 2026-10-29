"""Shared bilingual layout and renderer-based validation. No remote calls."""
import argparse
import json
import re
from pathlib import Path
from itertools import combinations
import matplotlib.pyplot as plt
from matplotlib.text import Text
from matplotlib.transforms import Bbox

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--lang', choices=('en', 'pt'), default='en')
ARGS = parser.parse_args()
LANG = ARGS.lang
OUT = ROOT / ('figures_pt' if LANG == 'pt' else 'figures')
OUT.mkdir(exist_ok=True)
TRANSLATIONS = json.loads((ROOT / 'figure_text_pt.json').read_text(encoding='utf-8'))


def tr(text):
    return TRANSLATIONS.get(text, text) if LANG == 'pt' else text


def wrap_pixels(text, artist, renderer, width):
    """Wrap explicit paragraphs on words using the actual font metrics."""
    lines = []
    fp = artist.get_fontproperties()
    for para in text.split('\n'):
        current = ''
        for word in para.split(' '):
            candidate = (current + ' ' + word).strip()
            measured = renderer.get_text_width_height_descent(candidate, fp, False)[0]
            if current and measured > width:
                lines.append(current); current = word
            else:
                current = candidate
        lines.append(current)
    return '\n'.join(lines)


def fit_box(ax, x, y, w, h, title, sub, color, fs, sfs, *, min_fontsize=None, padding=5.0):
    """Fit a title/subtitle stack inside its true display-space rectangle."""
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    p0, p1 = ax.transData.transform([(x, y), (x+w, y+h)])
    pad = padding
    width, height = p1[0]-p0[0]-2*pad, p1[1]-p0[1]-2*pad
    heading = ax.text(0, 0, title, ha='center', va='center', color=color,
                      fontsize=fs, fontweight='bold', linespacing=1.15)
    body = ax.text(0, 0, sub, ha='center', va='center', color=color,
                   fontsize=sfs, linespacing=1.18) if sub else None
    items = [heading] + ([body] if body else [])
    for step in range(45):
        scale = .97 ** step
        heading.set_fontsize(max(min_fontsize or 0, fs*scale))
        heading.set_text(wrap_pixels(title, heading, renderer, width))
        if body:
            body.set_fontsize(max(min_fontsize or 0, sfs*scale))
            body.set_text(wrap_pixels(sub, body, renderer, width))
        sizes = [t.get_window_extent(renderer) for t in items]
        gap = 5 if body else 0
        total = sum(b.height for b in sizes) + gap
        if total <= height and all(b.width <= width+.01 for b in sizes):
            break
    else:
        raise ValueError(f'Cannot fit box: {title}')
    top = (p0[1]+p1[1]+total)/2
    for item, size in zip(items, sizes):
        center = ((p0[0]+p1[0])/2, top-size.height/2)
        item.set_position(ax.transData.inverted().transform(center))
        item._figure_box = (x, y, w, h)
        top -= size.height+gap


def audit(fig, name):
    """Check text-text overlaps and diagram box containment at final layout."""
    original_dpi = fig.dpi
    if name.startswith('diag_'):
        # Audit the actual PNG renderer, including bold glyph metrics, rather
        # than trusting the lower-DPI interactive canvas used during wrapping.
        fig.set_dpi(300)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text().strip()
             and (t.axes is None or t.axes.get_visible())]
    boxes = [(t, t.get_window_extent(renderer)) for t in texts]
    overlaps = []
    for (a, ab), (b, bb) in combinations(boxes, 2):
        # Duplicated invisible tick copies can exist outside view limits.
        intersection = Bbox.intersection(ab, bb)
        if intersection and intersection.width > .8 and intersection.height > .8:
            overlaps.append([a.get_text(), b.get_text()])
    escaped = []
    for t, b in boxes:
        if hasattr(t, '_figure_box'):
            x,y,w,h = t._figure_box
            p0,p1 = t.axes.transData.transform([(x,y),(x+w,y+h)])
            if b.x0 < p0[0]+1 or b.x1 > p1[0]-1 or b.y0 < p0[1]+1 or b.y1 > p1[1]-1:
                escaped.append(t.get_text())
    clipped_boxes = []
    if name.startswith('diag_'):
        from matplotlib.patches import FancyBboxPatch
        for ax in fig.axes:
            for patch in ax.patches:
                if isinstance(patch, FancyBboxPatch):
                    b = patch.get_window_extent(renderer)
                    if b.x0 < ax.bbox.x0 or b.x1 > ax.bbox.x1 or b.y0 < ax.bbox.y0 or b.y1 > ax.bbox.y1:
                        clipped_boxes.append([round(v, 3) for v in (patch.get_x(), patch.get_y(), patch.get_width(), patch.get_height())])
    arrow_text_overlaps = []
    if name.startswith('diag_'):
        from matplotlib.patches import FancyArrowPatch
        from matplotlib.path import Path as MplPath
        def line_hits(a, b, bounds):
            low, high = 0., 1.
            for start, end, lo, hi in zip(a, b, (bounds.x0, bounds.y0), (bounds.x1, bounds.y1)):
                delta = end-start
                if abs(delta) < 1e-10:
                    if not lo <= start <= hi:
                        return False
                else:
                    u, v = sorted(((lo-start)/delta, (hi-start)/delta))
                    low, high = max(low,u), min(high,v)
                    if low > high:
                        return False
            return True
        for ax in fig.axes:
            for patch in ax.patches:
                if isinstance(patch, FancyArrowPatch):
                    path = patch.get_path().transformed(patch.get_transform())
                    segments, previous, start = [], None, None
                    # Never treat CLOSEPOLY's dummy (0,0) vertex as geometry.
                    # Flatten curves in display space, retaining subpath moves.
                    for vertices, code in path.iter_segments(curves=False, simplify=False):
                        point = tuple(vertices[-2:])
                        if code == MplPath.MOVETO:
                            previous = start = point
                        elif code == MplPath.CLOSEPOLY:
                            if previous is not None:
                                segments.append((previous, start))
                            previous = start
                        elif previous is not None:
                            segments.append((previous, point)); previous = point
                    for text, bounds in boxes:
                        if any(line_hits(a,b,bounds.padded(2)) for a,b in segments):
                            arrow_text_overlaps.append(text.get_text())
    report = {'figure':name, 'language':LANG, 'text_count':len(texts),
              'text_overlaps':overlaps, 'box_overflows':escaped, 'clipped_boxes':clipped_boxes,
              'scope':'Rendered text bounding boxes and diagram-box containment. Does not prove arrow/curve clearance.'}
    if name.startswith('diag_'):
        report.update(renderer_dpi=300, arrow_text_overlaps=arrow_text_overlaps,
                      min_box_font_pt=min(t.get_fontsize() for t in texts if hasattr(t, '_figure_box')),
                      bold_text_count=sum(t.get_fontweight() == 'bold' for t in texts),
                      scope='300-DPI actual regular/bold text bounds, box containment, and flattened arrow paths against text bounds (+2 px). Manual PNG inspection still required for composition and print-scale legibility.')
    (OUT / f'{name}.layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if overlaps or escaped or arrow_text_overlaps:
        print('LAYOUT', name, json.dumps({'overlaps':overlaps,'overflow':escaped,'arrow_text':arrow_text_overlaps},ensure_ascii=False))
    fig.set_dpi(original_dpi)
    if name.startswith('diag_') and (overlaps or escaped or clipped_boxes or arrow_text_overlaps):
        raise ValueError(f'Diagram layout audit failed: {name}; see {name}.layout.json')
    return report


def finish_figure(fig, name):
    diagram = name.startswith('diag_')
    # Translation precedes wrapping/layout; box text was translated before fitting.
    for t in fig.findobj(Text):
        if not hasattr(t, '_figure_box'):
            t.set_text(tr(t.get_text()))
    if not diagram:
        for ax in fig.axes:
            if LANG == 'pt':
                for axis in (ax.xaxis, ax.yaxis):
                    labels = [t.get_text() for t in axis.get_ticklabels()]
                    translated = [tr(label) for label in labels]
                    if translated != labels:
                        axis.set_ticks(axis.get_majorticklocs(), labels=translated)
            if name in ('fig_cost_by_model', 'fig_accuracy_by_model'):
                for tick in ax.get_xticklabels():
                    tick.set_rotation(90)
                    tick.set_ha('right')
            legend = ax.get_legend()
            if legend:
                ax.legend(legend.legend_handles, [t.get_text() for t in legend.get_texts()],
                          ncol=1, loc='upper left', bbox_to_anchor=(1.02, 1),
                          fontsize=legend.get_texts()[0].get_fontsize(),
                          frameon=legend.get_frame_on())
            ax.title.set_linespacing(1.3)
        fig.set_layout_engine('constrained')
        fig.get_layout_engine().set(h_pad=.16, w_pad=.12, hspace=.18, wspace=.14)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for ax in fig.axes:
            raw = ax.title.get_text()
            ax.title.set_text(wrap_pixels(raw, ax.title, renderer, ax.bbox.width))
            ax.set_title(ax.title.get_text(), pad=16)
        fig.canvas.draw()
    audit(fig, name)
