"""Render evaluation addendum and one paired-difference plot; local only."""
import html
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

R=Path(__file__).resolve().parents[1]
E=R/'data/reports-out/finalizacao-2026-10-28/evaluation'
D=json.loads((E/'reanalysis.json').read_text(encoding='utf-8'))
arms=['on_baseline_raw','on_graphify_raw','on_full','on_jev']
labels=['Baseline','Graphify hybrid','Auto + optimizer','Graphify + JEV']
fig,ax=plt.subplots(figsize=(7.2,3.4))
for i,a in enumerate(arms):
    v=D['rules']['strict'][a]['strata']['all']
    ax.errorbar(100*v['difference'],i,xerr=[[100*(v['difference']-v['lo'])],[100*(v['hi']-v['difference'])]],fmt='o',capsize=4,color='#166534' if a=='on_full' else '#334155')
ax.axvline(0,color='#64748b',ls='--',lw=.8)
ax.set_yticks(range(4),labels)
ax.set_xlabel('Strict-corrected difference vs OFF-A (percentage points)')
ax.set_title('Paired outcomes: 648 pairs per arm, 72 question clusters')
ax.invert_yaxis()
ax.grid(axis='x',alpha=.2)
fig.tight_layout()
for ext in ['pdf','svg','png']:
    fig.savefig(E/f'paired_strict.{ext}',dpi=300,bbox_inches='tight')
plt.close(fig)
styles=getSampleStyleSheet()
styles['BodyText'].fontSize=9
styles['BodyText'].leading=12
styles['BodyText'].spaceAfter=6
styles['Title'].fontSize=19
story=[]
lines=(E/'ADDENDUM.md').read_text(encoding='utf-8').splitlines()
i=0
width=A4[0]-84
while i<len(lines):
    line=lines[i]
    if not line.strip():
        i+=1;continue
    if line.startswith('|'):
        rows=[]
        while i<len(lines) and lines[i].startswith('|'):
            cells=[x.strip() for x in lines[i].strip('|').split('|')]
            if not all(set(x)<=set('-: ') for x in cells):
                rows.append([Paragraph(html.escape(x),styles['BodyText']) for x in cells])
            i+=1
        if rows:
            t=Table(rows,colWidths=[width/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e2e8f0')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.5,colors.grey),('GRID',(0,0),(-1,-1),.2,colors.lightgrey),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
            story.extend([t,Spacer(1,10)])
        continue
    if line.startswith('# '):
        story.append(Paragraph(html.escape(line[2:]),styles['Title']))
    elif line.startswith('## '):
        story.append(Paragraph(html.escape(line[3:]),styles['Heading2']))
    else:
        story.append(Paragraph(html.escape(line),styles['BodyText']))
    i+=1
story.extend([Spacer(1,12),Image(str(E/'paired_strict.png'),width=width,height=width*3.4/7.2)])
def footer(canvas,doc):
    canvas.setFont('Helvetica',8)
    canvas.drawString(42,24,'Anamnesia evaluation addendum - offline reanalysis, 28 October 2026')
    canvas.drawRightString(A4[0]-42,24,str(doc.page))
SimpleDocTemplate(str(E/'Anamnesia_Benchmark_Addendum_2026-10-28.pdf'),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer)
print('rendered addendum and paired plot',E)
