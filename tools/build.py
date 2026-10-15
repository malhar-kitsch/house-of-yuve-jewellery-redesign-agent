# Build data/pairs/<id>/ folders from the spec below.
# Source refs: "A08@4" = video frame 4 of 12; "B06[x0,y0,x1,y1]" = crop; "B07~p0" = auto-detected panel; "A03" = whole photo.
import json, os, re, subprocess, sys
from PIL import Image
D=sys.argv[1]; SRC=f"{D}/src"
PAIRS = [
 ("gm01_patoda_choker","gewelsbymona","Old gold necklace -> choker with pearl stringing, meena and Patoda-saree-inspired motifs",
   {"before":["A03"],"after":["A06","A02"],"combined":["A04"],"inspiration":["A05"]},"high"),
 ("gm02_old_era_necklace","gewelsbymona","18kt gold necklace + studs -> multi-strand gemstone bead necklaces with Patoda/enamel pendant",
   {"before":["A09"],"after":["A10","A11"]},"medium - after images look like same post but not confirmed"),
 ("gm03_bangle_to_pendant","gewelsbymona","Grandmother's 22kt plain bangle -> elaborate kundan pendant on emerald bead + rice pearl strands",
   {"before":["A08@0"],"after":["A08@4","A08@6","A08@10"]},"high"),
 ("gm04_long_necklace_to_kundan","gewelsbymona","Heavy long gold necklace -> kundan choker and earrings in 18kt",
   {"before":["A13@0"],"process":["A13@2"],"after":["A13@5","A13@6"],"worn":["A13@3"],"combined":["A13@10"]},"high"),
 ("gm05_necklace_to_pearl_choker","gewelsbymona","Gold collar necklace + studs -> pearl-and-gold choker with blue/white enamel centre and matching earrings",
   {"before":["A16@1"],"after":["A16@4","A16@5","A16@8"],"combined":["A16@10"]},"high"),
 ("gm06_bangle_ad","gewelsbymona","Old bangle -> pearl and ruby kada (from an ad film, possibly AI-generated)",
   {"before":["A20@2"],"process":["A20@5"],"after":["A20@7"]},"low"),
 ("gm07_light_choker_to_statement","gewelsbymona","Light heirloom choker -> heavier statement choker with emerald drops and pearl ghungroos",
   {"before":["A21@3"],"process":["A21@4","A21@6"],"after":["A21@8","A21@9","A21@7"],"combined":["A21@11"]},"high"),
 ("gm08_necklace_to_navratna","gewelsbymona","18kt gold necklace -> navratna cabochon + kundan choker with pearls",
   {"before":["A22@0"],"after":["A22@7","A22@8","A22@9","A22@4"],"combined":["A22@11"]},"high"),
 ("gm09_necklace_to_kundan_pearl","gewelsbymona","Old gold necklace -> layered pearl/green-bead necklace with kundan pendant",
   {"before":["A23@0"],"after":["A23@6","A23@8"],"combined":["A23@11"]},"high"),
 ("kl01_haar_to_set","kivlo","Long gold haar -> enamel/stone statement necklace, earrings and bangle",
   {"after":["A01@3","A01@5","A01@6"],"combined":["A01@0"]},"medium - before only shown inside combined card"),
 ("kl02_polki_tanzanite","kivlo","Polki choker -> polki necklace with tanzanite drops + long earrings",
   {"before":["B12~p0","B01[110,215,555,560]"],"after":["B01[110,555,965,1141]"],"process":["B11~p0","B11~p1"]},"high"),
 ("kl03_watch_to_bracelet","kivlo","Old gold watch -> bracelet with large centre stone and diamonds",
   {"before":["B02~p0"],"after":["B02~p1","B13@7","B13@8"]},"high"),
 ("kl04_temple_set_to_coral_haar","kivlo","Old temple gold pieces -> long coral bead haar with temple pendant + earrings",
   {"before":["B05~p0","B06[130,345,460,955]"],"after":["B06[320,330,1080,1240]","B15@6"]},"high"),
 ("kl05_bangles_upgrade","kivlo","Plain gold bangles -> heirloom bangles with beads and drops",
   {"before":["B07~p0"],"after":["B07~p1","B14@6"]},"high"),
 ("kl06_simple_set_to_pearl_haar","kivlo","Simple gold necklace set -> multi-strand pearl haar with green beads, bigger pendant + earrings",
   {"before":["B08[120,340,530,920]","B16@1"],"after":["B08[400,400,1080,1330]","B16@5","B16@6"]},"high"),
 ("kl07_necklace_to_statement","kivlo","Light gold necklace + earrings -> stone-set statement necklace + jhumkas",
   {"before":["B09~p0","B10~p0"],"after":["B10~p1","B17@8"]},"high"),
 ("kl08_hoops_to_earrings","kivlo","Navratna hoop earrings -> teardrop stone statement earrings",
   {"before":["B19[165,285,615,560]"],"after":["B19[420,530,915,1170]"]},"high"),
 ("kl09_long_necklace_to_layered","kivlo","Long gold necklace -> layered pearl/kundan haar + earrings",
   {"before":["B20~p0"],"after":["B20~p1"]},"high"),
 ("kl10_bangles_with_diamonds","kivlo","Four gold bangles -> bangles with diamond accents",
   {"before":["B21~p0"],"after":["B21~p1"]},"high"),
 ("kl11_uncut_pendant_emerald","kivlo","Uncut diamond pendant set -> long emerald bead necklace with the pendant + earrings",
   {"before":["B22[45,350,500,1180]"],"after":["B22[500,320,1020,1270]"]},"high"),
 ("kl12_mothers_necklace","kivlo","Mother's gold coin necklace -> new necklace (shown worn)",
   {"before":["B23[60,465,490,1170]"],"after":["B23[360,330,1080,1350]"]},"medium - after only shown on person"),
 ("kl13_long_set_to_pearl_haar","kivlo","Long gold rani haar set -> pearl haar with kundan pendant, earrings and bangles",
   {"before":["B24[125,370,470,1080]"],"after":["B24[420,350,1080,1350]"]},"high"),
 ("kl14_earrings_to_necklace","kivlo","Old chandbali earrings -> pearl-strand necklace with the earrings as pendant",
   {"before":["B28[100,370,530,690]"],"after":["B28[520,580,955,1240]"]},"high"),
 ("kl15_pendant_chain_to_ruby_beads","kivlo","Long chain with round pendant + earrings -> ruby bead multi-strand necklace + statement earrings",
   {"before":["B04@0"],"after":["B04@2","B04@5","B03@11"],"combined":["B04@8"]},"high"),
]
STYLE = ["A07@6","A12@0","A15@6","A17","A18@6","A18@9","A19@11","B18~p0","B25","B26@6"]
INCOMPLETE = [("kl16_coin_necklace","kivlo","Coin necklace - before and in-process only, no after",{"before":["B27~p0"],"process":["B27~p1"]})]

def dur(v): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",v]))
def make(ref,out):
    m=re.match(r"(\w\d\d)(?:@(\d+)|\[(.+)\]|~(p\d))?$",ref); sid,k,box,pan=m.groups()
    if k is not None:
        v=f"{SRC}/{sid}.mp4"; t=(int(k)+0.5)*dur(v)/12
        subprocess.check_call(["ffmpeg","-v","error","-y","-ss",f"{t:.2f}","-i",v,"-frames:v","1","-q:v","2",out])
    elif box: Image.open(f"{SRC}/{sid}.jpg").convert("RGB").crop(tuple(map(int,box.split(",")))).save(out,quality=95)
    elif pan: Image.open(f"{D}/crops/{sid}_{pan}.jpg").save(out,quality=95)
    else: Image.open(f"{SRC}/{sid}.jpg").convert("RGB").save(out,quality=95)

index=[]
def build(root,pid,brand,desc,roles,conf):
    d=f"{D}/{root}/{pid}"; os.makedirs(d,exist_ok=True); files={}
    for role,refs in roles.items():
        files[role]=[]
        for i,r in enumerate(refs,1):
            fn=f"{role}_{i}.jpg"; make(r,f"{d}/{fn}"); files[role].append({"file":fn,"source":r})
    meta={"id":pid,"brand":brand,"transformation":desc,"confidence":conf,"files":files}
    json.dump(meta,open(f"{d}/meta.json","w"),indent=2); index.append({**meta,"folder":f"{root}/{pid}"})
for p in PAIRS: build("pairs",*p)
for p in INCOMPLETE: build("incomplete",*p,"n/a")
os.makedirs(f"{D}/style_refs",exist_ok=True)
for r in STYLE: make(r,f"{D}/style_refs/{r.replace('@','_f').replace('~','_')}.jpg")
json.dump({"pairs":index,"style_refs":STYLE},open(f"{D}/dataset.json","w"),indent=2)
print(len(PAIRS),"pairs")
