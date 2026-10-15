"""Generate a labeled mock layout screenshot. Does not represent a real game capture."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from PIL import ImageGrab
from hud_ui_r19 import GameHUD

root=tk.Tk();root.title('게임 화면 자리 (시연용 · 실제 우마무스메 아님)')
root.geometry('835x700+50+50')
root.configure(bg='#111728')
f=tk.Frame(root,bg='#111728');f.pack(fill='both',expand=True)
tk.Label(f,text='게임 화면 위치 시연',font=('DejaVu Sans',18,'bold'),bg='#111728',fg='white').pack(pady=(20,2))
tk.Label(f,text='아래 훈련 버튼과 위 표시는 UI 배치 예시입니다. 게임 자동 인식 결과가 아닙니다.',font=('DejaVu Sans',10),bg='#111728',fg='#bbb').pack()
canvas=tk.Canvas(f,width=800,height=580,bg='#1a2c43',bd=0,highlightthickness=0);canvas.pack(padx=12,pady=10)
canvas.create_rectangle(35,38,760,310,fill='#294a62',outline='#53728f')
canvas.create_text(395,150,text='GAME CONTENT AREA',font=('DejaVu Sans',29,'bold'),fill='#94b2c5')
labels=['스피드','스태미나','파워','근성','지능']
for ix,name in enumerate(labels):
    x=38+ix*153
    canvas.create_rectangle(x,395,x+143,493,fill='#2a3c58',outline='#667f9e',width=2)
    canvas.create_text(x+72,451,text=name,font=('DejaVu Sans',13,'bold'),fill='#f1f5fd')
canvas.create_oval(45,402,172,488,outline='#76e5a3',width=4)
canvas.create_rectangle(35,350,360,379,fill='#1a2e32',outline='#76e5a3')
canvas.create_text(45,364,text='스피드 훈련 · 수동 위치 지정 예시',anchor='w',fill='#a6f5c9',font=('DejaVu Sans',11,'bold'))
context={'event':'챔피언스 미팅','style':'선입','course':'교토 2000m (사용자 설정)','targets':{'스피드':1700,'스태미나':1200,'파워':1300,'근성':1100,'지능':1200},'stats':{'스피드':930,'스태미나':711,'파워':760,'근성':520,'지능':743},'required_skills':[{'name':'왕수','status':'미획득'},{'name':'중거리 코너○','status':'획득'}], 'skill_checked':True, 'skill_advice':{'왕수':{'verdict':'우선 검토'}},'training_checked':True,'training_rankings':[{'name':'스피드'}]}
hud=GameHUD(root,lambda:context)
hud.open()
class Window:
    x,y,width,height=50,50,835,700
hud.update(Window(),[],'훈련',False,False)
root.update_idletasks();root.update()
from PIL import Image
bbox=(25,25,1325,785)
path=Path(__file__).with_name('R19_게임위표시_옆정보창_배치예시.png')
ImageGrab.grab(bbox=bbox).save(path)
print(path)
hud.close();root.destroy()
