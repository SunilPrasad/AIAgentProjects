from pathlib import Path
from io import BytesIO
import json, re, hashlib, argparse
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
from reportlab.pdfgen import canvas
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

parser=argparse.ArgumentParser(description='Prepare a complete digital reader PDF; no model calls.')
parser.add_argument('--book',required=True)
args=parser.parse_args()
definition=Path(args.book).resolve()
book=json.loads(definition.read_text(encoding='utf-8-sig'))
assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',book['id'])
base=(definition.parent/book.get('outputRoot','../output/books')).resolve()/book['id']
out=base/'sales/etsy'
out.mkdir(parents=True,exist_ok=True)
report=json.loads((base/'assembled/assembly-report.json').read_text())
original=base/'assembled'/(book['id']+'_interior_REVIEW.pdf')
assert hashlib.sha256(original.read_bytes()).hexdigest()==report['interiorSha256'], 'Assembly proof changed'
source=PdfReader(original)
writer=PdfWriter()
cover=report.get('coverSource')
front_count=1 if cover else 0
if cover:
    buffer=BytesIO()
    c=canvas.Canvas(buffer,pagesize=(432,648),invariant=1)
    c.drawImage(cover,0,0,432,648)
    c.save()
    writer.add_page(PdfReader(BytesIO(buffer.getvalue())).pages[0])
expected = []
for index, page in enumerate(source.pages):
    # Remove only the intentional final blank binding page from the reader edition.
    if index == len(source.pages)-1 and not page.extract_text().strip():
        continue
    expected.append(re.sub(r'\s+', ' ', page.extract_text()).strip())
    number = index+1
    offset = 0 if number % 2 else 9
    page.add_transformation(Transformation().translate(-offset, -9))
    box = RectangleObject([0, 0, 432, 648])
    page.mediabox = box
    page.cropbox = RectangleObject(box)
    page.trimbox = RectangleObject(box)
    writer.add_page(page)

for chapter in report['chapters']:
    writer.add_outline_item(chapter['subject'], chapter['firstPage']-1+front_count)
writer.add_metadata({'/Title':book['title'], '/Author':book.get('author',''), '/Subject':book.get('subtitle','')})

# Reader edition: compress raster payloads at their original dimensions; keep selectable text.
# The full-quality print masters are preserved separately.
seen = set()
image_count = 0
for page in writer.pages:
    for image in list(page.images):
        key = (image.indirect_reference.idnum, image.indirect_reference.generation)
        if key in seen:
            continue
        seen.add(key)
        pixels = image.image.size
        image.replace(image.image.convert('RGB'), quality=86, optimize=True)
        assert image.image.size == pixels
        image_count += 1
    page.compress_content_streams()
writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
path = out/(book['id']+'.pdf')
writer.write(path)
assert path.stat().st_size < 20_000_000, 'Exceeds Etsy upload limit'
final = PdfReader(path)
assert len(final.pages) == len(expected)+front_count
for index, text in enumerate(expected, front_count):
    assert re.sub(r'\s+', ' ', final.pages[index].extract_text()).strip() == text
assert final.metadata.author == book.get('author','')

renders = out/'previews'
renders.mkdir(parents=True, exist_ok=True)
doc = pdfium.PdfDocument(str(path))
for index in range(len(doc)):
    doc[index].render(scale=1.25).to_pil().save(renders/f'page-{index+1:03}.png')
for offset in range(0,len(doc),8):
    contact = Image.new('RGB',(1200,1000),'#dddddd')
    draw = ImageDraw.Draw(contact)
    for position,index in enumerate(range(offset,min(offset+8,len(doc)))):
        im = Image.open(renders/f'page-{index+1:03}.png')
        im.thumbnail((290,455))
        x, y = position%4*300, position//4*500
        contact.paste(im,(x,y+25))
        draw.text((x+5,y+5),f'READER PAGE {index+1}',fill='black')
    contact.save(renders/f'contact-{offset//8+1}.png')
doc.close()
verification = dict(pages=len(final.pages), bytes=path.stat().st_size, imagePayloads=image_count,
    exactInteriorTextVerified=True, author=book.get('author',''),
    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    edition='Digital reader edition; compressed images; original print masters retained')
(out/'verification.json').write_text(json.dumps(verification,indent=2))
print(json.dumps(verification,indent=2))
