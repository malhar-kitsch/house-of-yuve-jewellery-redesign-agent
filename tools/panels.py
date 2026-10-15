# Find photo panels on KivLo's plain cream background and crop them.
import sys, os, numpy as np
from PIL import Image
from scipy import ndimage
outdir=sys.argv[1]
for p in sys.argv[2:]:
    im=Image.open(p).convert("RGB"); a=np.asarray(im).astype(int)
    bg=np.median(np.concatenate([a[:20].reshape(-1,3),a[-20:].reshape(-1,3)]),axis=0)
    diff=np.abs(a-bg).sum(2)>60
    diff=ndimage.binary_opening(diff,iterations=3); diff=ndimage.binary_fill_holes(diff)
    lab,n=ndimage.label(diff); boxes=[]
    for s in ndimage.find_objects(lab):
        h,w=s[0].stop-s[0].start,s[1].stop-s[1].start
        if h*w>0.04*a.shape[0]*a.shape[1] and h>100 and w>100: boxes.append(s)
    id=os.path.basename(p).split('.')[0]
    for k,s in enumerate(sorted(boxes,key=lambda s:(s[1].start))):
        im.crop((s[1].start,s[0].start,s[1].stop,s[0].stop)).save(f"{outdir}/{id}_p{k}.jpg",quality=92)
    print(id, im.size, [(s[1].start,s[0].start,s[1].stop-s[1].start,s[0].stop-s[0].start) for s in boxes])
