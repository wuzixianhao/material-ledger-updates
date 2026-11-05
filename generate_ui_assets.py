"""Generate code-native theme primitives; build-time Pillow only."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / 'ui_assets'
OUT.mkdir(exist_ok=True)


def shape(name, size, box, fill, outline=None, stroke=1, radius=8):
    scale = 4
    im = Image.new('RGBA', (size[0]*scale, size[1]*scale))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle(tuple(v*scale for v in box), radius=radius*scale, fill=fill,
                           outline=outline, width=stroke*scale)
    im.resize(size, Image.Resampling.LANCZOS).save(OUT/(name+'.png'))


for name, stroke, color in [('normal',1,'#dce4ef'),('hover',1,'#9bbbea'),('focus',2,'#287aef')]:
    shape('field-'+name, (40,40), (1,1,38,38), '#f8fafc', color, stroke, 10)
for axis in ['v','h']:
    size = (24,60) if axis=='v' else (60,24)
    shape('track-'+axis, size, (1,1,size[0]-2,size[1]-2), '#f1f4f9', radius=10)
    for state,color,inset in [('normal','#b4c2d5',5),('hover','#839cbd',3),('pressed','#4c89dd',3)]:
        box = (inset,2,size[0]-inset-1,size[1]-3) if axis=='v' else (2,inset,size[0]-3,size[1]-inset-1)
        shape('thumb-'+axis+'-'+state,size,box,color,radius=8)
im = Image.new('RGBA',(64,64))
d=ImageDraw.Draw(im)
d.line([(16,24),(32,40),(48,24)],fill='#657b99',width=6,joint='curve')
im.resize((16,16),Image.Resampling.LANCZOS).save(OUT/'chevron.png')
