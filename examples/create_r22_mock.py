"""Create fake game-like training preview screenshots for OCR smoke tests only."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from live_training_r22 import NumericProfile,FieldBox,save_profile, SCREEN_FIELDS
from uma_core import STATS

here=Path(__file__).parent
font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
try: f=ImageFont.truetype(font,24); large=ImageFont.truetype(font,36)
except OSError:f=ImageFont.load_default();large=f
fields=SCREEN_FIELDS
values=[(68,1,5,3,2,30,4),(1,72,4,4,6,22,8),(3,2,83,6,2,28,9),(4,2,5,74,3,27,6),(3,2,3,4,67,25,1)]
rects={}
for i,k in enumerate(fields):
    row=i; y=178+row*61
    rects[k]=FieldBox(680/960, (y-10)/720, 790/960,(y+38)/720)
for idx,name in enumerate(STATS):
    image=Image.new('RGB',(960,720),'#121F33');d=ImageDraw.Draw(image)
    d.rectangle((25,30,935,680),outline='#32607A',width=3)
    d.text((55,55),'UMA TRAINER R22 / SIMULATED IMAGE',font=large,fill='#FFFFFF')
    d.text((55,115),f'TEST TAB  {idx+1}/5',font=large,fill='#FFE083')
    for j,field in enumerate(fields):
        y=178+j*61
        d.rounded_rectangle((55,y-9,825,y+46),radius=8,fill=('#27415B' if j%2==0 else '#1E344B'))
        d.text((90,y),['SPEED +','STAMINA +','POWER +','GUTS +','WISDOM +','SKILL PT +','FAIL %'][j],font=f,fill='#E1F0FF')
        d.text((682,y-2),str(values[idx][j]),font=large,fill='#FFFFFF')
    d.text((60,638),'ONLY SYNTHETIC TEST DATA — NOT KOREAN GAME SCREEN',font=f,fill='#FFBF83')
    image.save(here/f'r22_mock_{idx+1}.png')
profile=NumericProfile(width=960,height=720,boxes=rects)
save_profile(here/'r22_mock_roi.json',profile)
print('synthetic images + ROI created')
