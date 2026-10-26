"""Assemble approved chapter PDFs without rewriting text or recompressing artwork."""
from pathlib import Path
import io, json, hashlib, re, argparse, math
from html import escape
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ContentStream, RectangleObject, TextStringObject, ByteStringObject, ArrayObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser(description="Assemble reviewed chapters using a shared book definition; no model calls.")
parser.add_argument('--book', required=True)
parser.add_argument('--cover', help="Original front cover image; optional")
parser.add_argument('--inspect', action='store_true')
args = parser.parse_args()
DEFINITION = Path(args.book).resolve()
BOOK = json.loads(DEFINITION.read_text(encoding='utf-8-sig'))
BOOK_ID = BOOK['id']
assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', BOOK_ID), 'Unsafe book ID'
SUBJECTS = BOOK['subjects']
assert SUBJECTS and len({s['id'] for s in SUBJECTS}) == len(SUBJECTS)
assert all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',s['id']) for s in SUBJECTS)
ROOT = (DEFINITION.parent / BOOK.get('outputRoot','../output/books')).resolve() / BOOK_ID
if BOOK.get('selectionId'):
    assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', BOOK['selectionId']), 'Unsafe selection ID'
    ROOT = ROOT / 'selections' / BOOK['selectionId']
OUT = ROOT / 'assembled'
TMP = OUT / 'previews'
COVER = Path(args.cover).resolve() if args.cover else None
if COVER is None and BOOK.get('coverImage'):
    COVER = (DEFINITION.parent / BOOK['coverImage']).resolve()
FONTS = Path(__file__).resolve().parents[1] / 'GreatIndians.Factory/assets/fonts'
if args.inspect:
    print(json.dumps(dict(book=BOOK['title'],profile=BOOK.get('profile','nonfiction'),chapters=len(SUBJECTS),input=str(ROOT/'illustrated'),output=str(OUT),cover=str(COVER) if COVER else None),indent=2))
    raise SystemExit(0)
OUT.mkdir(parents=True,exist_ok=True)
TMP.mkdir(parents=True,exist_ok=True)
for name, file in [('Serif','Regular'),('SerifBold','Bold')]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / f'LiberationSerif-{file}.ttf')))
IVORY, BLUE, INK, GOLD = '#FFFDF6', '#0C348B', '#1D2636', '#B16A14'
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def norm(text): return re.sub(r'\s+', ' ', text).strip()
def sheet(draw, width=432, height=648):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width,height), invariant=1)
    draw(c)
    c.save()
    return PdfReader(io.BytesIO(buffer.getvalue())).pages[0]
def background(c, width=432, height=648):
    c.setFillColor(HexColor(IVORY)); c.rect(0,0,width,height,fill=1,stroke=0)
def paragraph(c, text, x, top, width, size=12.1, colour=INK, bold=False, align=0):
    p = Paragraph(escape(text), ParagraphStyle('book', fontName='SerifBold' if bold else 'Serif',
        fontSize=size, leading=size*1.4, textColor=HexColor(colour), alignment=align))
    _, h = p.wrap(width, 600)
    p.drawOn(c,x,top-h)
    return top-h

chapters=[]
for number, subject in enumerate(SUBJECTS,1):
    folder = ROOT/'illustrated'/f"chapter_{number:02}_{subject['id']}"
    candidates=[]
    for status_file in folder.glob('*/status.json'):
        s=json.loads(status_file.read_text(encoding='utf-8-sig'))
        if s['status']=='PDF_REVIEW_PASSED': candidates.append((status_file.stat().st_mtime,status_file,s))
    assert candidates, f'No approved chapter: {folder}'
    _, status_file, s=max(candidates)
    assert sha(s['final']) == s['pdfSha256'], 'Approved PDF changed'
    assert sha(status_file.parent/'source.md') == s['sourceSha256'], 'Retained manuscript changed'
    assert any(s['pdfSha256'] == json.loads(p.read_text(encoding='utf-8-sig')).get('PdfSha256') for p in status_file.parent.glob('layout-*.json')), 'No matching layout manifest'
    layout = next(json.loads(p.read_text(encoding='utf-8-sig')) for p in status_file.parent.glob('layout-*.json') if json.loads(p.read_text(encoding='utf-8-sig')).get('PdfSha256') == s['pdfSha256'])
    credit_pages = {t['Page'] for t in layout['Text'] if t['Kind'] == 'image-credit'}
    manuscript=json.loads((status_file.parent/'manuscript.json').read_text(encoding='utf-8-sig'))
    assert manuscript['Subject'] == subject['name'], 'Chapter identity mismatch'
    chapters.append(dict(status=s, manuscript=manuscript, folder=status_file.parent,credit_pages=credit_pages))
assert len(chapters)==len(SUBJECTS)
contents_pages=math.ceil(len(chapters)/12)
starts=[]; page_number=2+contents_pages
for ch in chapters:
    starts.append(page_number); page_number+=ch['status']['pages']

def title(c):
    background(c)
    c.setStrokeColor(HexColor(GOLD)); c.line(65,530,367,530)
    paragraph(c,BOOK['title'],45,490,342,30,BLUE,True,1)
    paragraph(c,BOOK.get('subtitle',''),55,345,322,16,INK,False,1)
    paragraph(c,f"FOR READERS AGES {BOOK.get('audienceMinAge',8)}–{BOOK.get('audienceMaxAge',12)}",55,265,322,12,GOLD,True,1)
    c.line(65,190,367,190)
def contents(c, batch=0):
    background(c)
    paragraph(c,'Contents',55,565,322,22,BLUE,True)
    y=500
    for ch,start in list(zip(chapters,starts))[batch*12:(batch+1)*12]:
        m=ch['manuscript']; number=m['ChapterNumber']
        c.setFillColor(HexColor(GOLD)); c.setFont('SerifBold',11); c.drawString(55,y,str(number).zfill(2))
        c.setFillColor(HexColor(INK)); c.setFont('Serif',12.1); c.drawString(84,y,m['Subject'])
        c.setFillColor(HexColor(BLUE)); c.drawRightString(377,y,str(start)); y-=38

trim_pages=[sheet(title)]+[sheet(lambda c,batch=batch:contents(c,batch)) for batch in range(contents_pages)]
expected=[]
manifest=[]
for ch,start in zip(chapters,starts):
    reader=PdfWriter(clone_from=ch['status']['final'])
    m=ch['manuscript']
    body=[]
    for local,original in enumerate(reader.pages,1):
        before=original.extract_text()
        stream=ContentStream(original.get_contents(),reader)
        size=None; removed=0; operations=[]
        for operands, operator in stream.operations:
            if operator==b'Tf': size=float(operands[1])
            if operator in (b'Tj',b'TJ',b"'",b'"') and size==9:
                assert operator==b'Tj' and str(operands[0])==str(local), 'Unexpected footer text'
                removed+=1
                continue
            def preserve_bytes(value):
                if isinstance(value,TextStringObject): return ByteStringObject(value.original_bytes)
                if isinstance(value,ArrayObject): return ArrayObject([preserve_bytes(v) for v in value])
                return value
            operations.append(([preserve_bytes(v) for v in operands],operator))
        assert removed==1, 'Footer must be removed, not hidden behind an overlay'
        stream.operations=operations
        original.replace_contents(stream)
        content=original.extract_text()
        assert norm(before)==norm(content+' '+str(local)), repr([(i,ord(a),ord(b)) for i,(a,b) in enumerate(zip(norm(before),norm(content+' '+str(local)))) if a!=b])
        if local not in ch["credit_pages"]: body.append(content)
        global_number=len(trim_pages)+1
        # Keep the inner gutter on the binding side when a chapter starts on a left page.
        original_left=54.96 if local%2 else 50.4
        target_left=54.96 if global_number%2 else 50.4
        page=sheet(background)
        page.merge_transformed_page(original,Transformation().translate(target_left-original_left,0))
        def footer(c, number=global_number):
            c.setFont('Serif',9); c.setFillColor(HexColor('#213A73'))
            c.drawCentredString(216,24,str(number))
        page.merge_page(sheet(footer))
        trim_pages.append(page)
        expected.append((global_number,norm(content)))
    source=norm(m['Title']+' '+' '.join(p['Text'] for p in m['Paragraphs']))
    chapter_text=norm(' '.join(body))
    chapter_text=re.sub(r'^CHAPTER\s+\d+\s+', '',chapter_text)
    assert chapter_text==source, f"Source mismatch: {m['Subject']}"
    manifest.append(dict(subject=m['Subject'],firstPage=start,pages=len(reader.pages),sourcePdf=ch['status']['final'],
        sourcePdfSha256=ch['status']['pdfSha256'],sourceMarkdownSha256=ch['status']['sourceSha256']))
if len(trim_pages)%2: trim_pages.append(sheet(background))

# Bleed is outside the fore edge and 9pt above/below the trim; trim is still 6 x 9 inches.
writer=PdfWriter()
for number, page in enumerate(trim_pages,1):
    offset=0 if number%2 else 9
    bleed=sheet(lambda c:background(c,441,666),441,666)
    bleed.merge_transformed_page(page,Transformation().translate(offset,9))
    bleed.trimbox=RectangleObject([offset,9,offset+432,657])
    writer.add_page(bleed)
for ch,start in zip(chapters,starts): writer.add_outline_item(ch['manuscript']['Subject'],start-1)
writer.add_metadata({'/Title':BOOK['title'],'/Subject':'Complete interior review proof','/Author':BOOK.get('author','')})
interior=OUT/(BOOK_ID+'_interior_REVIEW.pdf')
writer.write(interior)
reopened=PdfReader(interior)
for number,content in expected:
    assert norm(reopened.pages[number-1].extract_text())==norm(content+' '+str(number)), 'Assembled text changed'
with pdfplumber.open(interior) as pdf:
    for number,page in enumerate(pdf.pages,1):
        assert (page.width,page.height)==(441,666)
        assert all(ch['x0']>=18 and ch['x1']<=423 and ch['top']>=18 and ch['bottom']<=648 for ch in page.chars)

# Cover proof: preserve supplied front artwork; back/spine are editable vector design.
spine=len(trim_pages)*0.002347*72
cover_width=432*2+spine+18
def wrap(c):
    c.setFillColor(HexColor('#082C59')); c.rect(0,0,cover_width,666,fill=1,stroke=0)
    front=9+432+spine
    c.drawImage(str(COVER),front,9,width=432,height=648)
    c.setStrokeColor(HexColor('#E6B665')); c.line(55,565,385,565)
    y=paragraph(c,BOOK['title'],55,530,330,24,'#F3CB7B',True)
    y=paragraph(c,BOOK.get('backCoverText',BOOK.get('subtitle','')),55,y-30,330,14,'#FFFDF6')
    y=paragraph(c,'Discover: '+', '.join(s['name'] for s in SUBJECTS)+'.',55,y-22,330,12,'#FFFDF6')
    paragraph(c,f"FOR READERS AGES {BOOK.get('audienceMinAge',8)}–{BOOK.get('audienceMaxAge',12)}",55,y-30,330,12,'#F3CB7B',True)
    # Unlabelled white area for the eventual KDP barcode; no invented ISBN.
    c.setFillColor(HexColor('#FFFFFF')); c.rect(273,36,144,86.4,fill=1,stroke=0)
cover_pdf=None
if COVER is not None:
    cover_writer=PdfWriter(); cover_writer.add_page(sheet(wrap,cover_width,666))
    cover_writer.add_metadata({'/Title':BOOK['title']+' - cover review','/Author':BOOK.get('author','')})
    cover_pdf=OUT/(BOOK_ID+'_cover_REVIEW.pdf'); cover_writer.write(cover_pdf)

all_renders=[]
for path in [p for p in [interior,cover_pdf] if p is not None]:
    doc=pdfium.PdfDocument(str(path))
    for index in range(len(doc)):
        rendered=doc[index].render(scale=1.35).to_pil()
        dest=TMP/f'{path.stem}-{index+1:03}.png'; rendered.save(dest)
        all_renders.append((path.stem,index+1,dest))
    doc.close()
for offset in range(0,len(all_renders),8):
    group=all_renders[offset:offset+8]
    contact=Image.new('RGB',(1200,1000),'#dddddd'); draw=ImageDraw.Draw(contact)
    for idx,(name,page,path) in enumerate(group):
        im=Image.open(path); im.thumbnail((290,455))
        x=(idx%4)*300; y=(idx//4)*500
        contact.paste(im,(x,y+25)); draw.text((x+5,y+5),f'{"COVER" if "Cover" in name else "INTERIOR"} {page}',fill='black')
    contact.save(TMP/f'contact-{offset//8+1}.png')
report=dict(interiorPages=len(trim_pages),chapterPages=sum(ch['status']['pages'] for ch in chapters),
    interiorSha256=sha(interior),coverSha256=sha(cover_pdf) if cover_pdf else None,coverPixels=list(Image.open(COVER).size) if COVER else None,
    coverEffectivePpi=min(Image.open(COVER).width/6,Image.open(COVER).height/9) if COVER else None,printStatus='REVIEW ONLY: inspect every page, cover resolution/bleed and physical proof before publication',
    spineInches=spine/72,chapters=manifest,authorDisplayed=False,bookId=BOOK_ID,author=BOOK.get('author',''),coverSource=str(COVER) if COVER else None)
(OUT/'assembly-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='chapters'},indent=2))
