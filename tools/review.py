import sys, glob, os
from PIL import Image, ImageDraw, ImageFont
out, dirs = sys.argv[1], sys.argv[2:]
f=ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc",18); T=200; rows=[]
for d in dirs:
    fs=sorted(glob.glob(d+"/before_*.jpg"))+sorted(glob.glob(d+"/after_*.jpg"))
    r=Image.new("RGB",(T*6+160,T),"white"); dr=ImageDraw.Draw(r); dr.text((4,4),os.path.basename(d)[:14],fill="black",font=f)
    for i,p in enumerate(fs[:6]):
        im=Image.open(p); im.thumbnail((T-4,T-20)); r.paste(im,(160+i*T,18)); dr.text((160+i*T,0),os.path.basename(p)[:-4],fill="red" if "before" in p else "green",font=f)
    rows.append(r)
g=Image.new("RGB",(rows[0].width,T*len(rows)),"white")
for i,r in enumerate(rows): g.paste(r,(0,i*T))
g.save(out,quality=80)
