#!/usr/bin/env python3
"""Nederland 2027. Vector PDF design, preview and print master.
Selected first design (left photo/sidebar), NOT the rejected editorial concept.\nStandalone reproducible specimen; does not alter the live shop or bot.
"""
from pathlib import Path
import calendar, datetime as dt, json, math
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
import fitz

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)
ASSETS=ROOT.parent/'assets'
FONT_CACHE=ROOT/'.font-cache'
FONT_CACHE.mkdir(exist_ok=True)
from fontTools.ttLib import TTFont as FontToolsFont
from fontTools.varLib.instancer import instantiateVariableFont
for family,weights in [('Onest',[400,500,600,700]),('Rubik',[400,500,600])]:
    for weight in weights:
        target=FONT_CACHE/f'{family}-{weight}.ttf'
        if not target.exists():
            with FontToolsFont(ASSETS/f'{family}.ttf') as variable:
                instantiateVariableFont(variable,{'wght':weight},inplace=True).save(target)
DATA=json.loads((ROOT/'data-original.json').read_text())
MM=72/25.4
W,H=297,210
INK='#252724'; MUT='#747873'; LINE='#D6DAD3'; SOFT='#F7F8F5'
ORANGE='#FC9740'; DARKORANGE='#AA4B07'; PEACH='#FFF1E3'
RED='#B53531'; PINK='#AE4272'; GREEN='#DDE9DE'; GREENTEXT='#42634C'
NL=['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december']
for family,weights in [('Onest',[400,500,600,700]),('Rubik',[400,500,600])]:
    for weight in weights:
        pdfmetrics.registerFont(TTFont(f'{family}{weight}',str(FONT_CACHE/f'{family}-{weight}.ttf')))

# Data changes are local, explicit and reversible.
EV=[]
for ev in DATA['events']:
    e=ev.copy()
    if e['label']=='Выборы': continue # community editorial boundary: no politics
    if e['m']==2 and e['d']==1 and e['kind']=='dead':
        e.update(m=1,d=31,label='Оформить новую zorgverzekering')
    if e['m']==5 and e['d']==1 and e['kind']=='dead':
        e.update(m=4,d=30,label='Aangifte: до 1 мая¹')
    if e['label']=='Aangifte открыта':e['label']='Aangifte за 2026¹';e['kind']='trad'
    if e['label']=='Podslushano.nl 3 года':e['label']='Podslushano.nl: 3 года'
    if e['label']=='Light Festival до 17.01':e['label']='Light Festival: финал'
    if e['label']=='Keukenhof открыт':e['label']='Keukenhof: открытие'
    if e['label']=='Keukenhof закрыт':e['label']='Keukenhof: финал'
    if e['label']=='Vrouwendag · 8 Марта':e['label']='8 Марта · Vrouwendag'
    if e['label']=='Sinterklaas · Pakjesavond':e['label']='Sinterklaas / Pakjesavond'
    if e['label']=='Zorgverzekering: срок':e['label']='Отменить zorgverzekering'
    if e['label']=='Летнее время':e['label']='Zomertijd · +1 час'
    if e['label']=='Зимнее время':e['label']='Wintertijd · −1 час'
    if e['label'] in ['Veteranendag','Burendag','Museumnacht']:e['label']+='*'
    if e['label']=='Leidens Ontzet':e['label']='Leidens Ontzet²'
    # Compact genuine Dutch compounds without changing their spelling.
    EV.append(e)
EV += [dict(m=1,d=20,label='Voorleesdagen: 20–31.01',kind='trad'),
       dict(m=10,d=30,label='Amsterdam Marathon',kind='trad'),
       dict(m=10,d=31,label='Marathon: день 2',kind='trad')]
# An unambiguous specimen of the existing personalization feature.
EV.append(dict(m=4,d=18,label='Ваша дата · пример',kind='me'))
EVENTS={}
for e in EV:EVENTS.setdefault((e['m'],e['d']),[]).append(e)
VAC=[v for v in DATA['vacations'] if 'Z' in v['regions']]

CONTENT={
1:('Зимний город','Amsterdam','Устрицы из Zeeland и первые букеты тюльпанов.',
   '16.01 · Tulpendag. До 17.01 · Amsterdam Light Festival.',
   'Проверьте январскую loonstrook','Сверьте часы, ставку и удержания. Сохраните годовые документы для aangifte.',
   '31.01 · новая zorgverzekering, если прежнюю отменили до 31.12.'),
2:('Время Carnaval','Amsterdam','Подснежники и длинные прогулки между дождями.',
   '6–9.02 · Carnaval в Maastricht и Den Bosch. Программа зависит от города.',
   'Сохраните aanslag','В письмах от gemeente и waterschap проверьте сумму, срок и варианты оплаты.',
   'Voorjaarsvakantie: даты школы могут отличаться от рекомендованных.'),
3:('Первые цветы','Amsterdamse Bos','Крокусы, нарциссы и первые цветущие деревья.',
   'Bloesempark: цветение зависит от погоды. Keukenhof: с 18.03.',
   'Подготовьте aangifte','При подаче до 1 апреля Belastingdienst сообщает результат до 1 июля.¹',
   '¹ Срок и тип aangifte — в вашем письме. 28.03 · часы на час вперёд.'),
4:('Месяц тюльпанов','Hillegom / Lisse','Тюльпановые поля и начало сезона спаржи.',
   '17.04 · Bloemencorso. 27.04 · Koningsdag.',
   'Фотографируйте с дорожки','В цветочные поля заходят только с разрешения владельца. Для прогулки выбирайте открытые маршруты.',
   '¹ Aangifte обычно подают до 1 мая; точный срок указан в aangiftebrief.'),
5:('Больше света','Zaanse Schans','Белая спаржа, свежая зелень и вечера на улице.',
   'Мельницы Zaanse Schans. Keukenhof открыт до 09.05 включительно.',
   'Уточните свободные дни','Праздник в календаре не всегда означает выходной. Проверьте свой CAO или трудовой договор.',
   'Vakantiegeld: дату выплаты и сумму смотрите в loonstrook и договоре.'),
6:('Ближе к морю','Scheveningen','Клубника, Hollandse Nieuwe и морской воздух.',
   'Scheveningen: прогулка по пляжу и набережной. Для Vlaggetjesdag проверьте анонс.',
   'Спланируйте летний отпуск','Сверьте остаток vakantie-uren и согласуйте даты заранее. Каникулы Zuid начинаются 24 июля.',
   '24.06 · традиционное завершение сезона спаржи. * Дата по ежегодному правилу.'),
7:('Лето без спешки','Marker Wadden','Черешня, вишня и длинные светлые вечера.',
   '20–23.07 · Vierdaagse в Nijmegen. Для Marker Wadden проверьте рейсы парома.',
   'Перед поездкой','Проверьте документы, билеты и покрытие страховки. Сохраните важные номера офлайн.',
   'Zomervakantie Zuid: 24.07–05.09. Другие регионы отдыхают в свои даты.'),
8:('Вересковое лето','Asselsche Heide / Veluwe','В конце лета heide окрашивает поля в лиловый.',
   'Veluwe: пешие и велосипедные маршруты вдоль вересковых полей.',
   'Проверьте правила маршрута','Для собак, велосипедов и прогулок вне троп действуют местные ограничения. Они указаны у входа.',
   'Летние каникулы Zuid продолжаются весь август, до 5 сентября.'),
9:('Возвращение в ритм','Zeelandbrug / Oosterschelde','Устрицы в Zeeland и первые осенние краски.',
   '11–12.09 · Open Monumentendag. Список открытых зданий публикуют организаторы.',
   'Обновите семейный план','Запишите школьные studiedagen, кружки и встречи. Они не входят в общие schoolvakanties.',
   '* Burendag: предварительно по ежегодному правилу. Проверьте анонс.'),
10:('Поезд в осень','Rheden / Gelderland','Осенние леса, грибы и тёплые напитки после прогулки.',
    'Veluwe: маршруты среди осенних деревьев. 30–31.10 · Amsterdam Marathon.',
    'Проверьте Mijn toeslagen','При изменении дохода или состава семьи проверьте данные и обновите их при необходимости.',
    '² 03.10 · памятная дата; праздничную программу Leiden проверяйте отдельно.'),
11:('Вечерние огни','Oudegracht / Utrecht','Огни на каналах, устрицы и первые зимние витрины.',
    'Utrecht: прогулка по Oudegracht. Дату приезда Sinterklaas уточняйте в своём городе.',
    'Сравните zorgverzekering','Смотрите не только premie, но и покрытие, договоры с клиниками и условия полиса на 2028 год.',
    '* Museumnacht: предварительная дата, требуется анонс организатора.'),
12:('Дом, свет, декабрь','Vrijthof / Maastricht','Oliebollen, ярмарки и ужины с близкими.',
    'Рождественские маршруты в Maastricht и Valkenburg. Программы уточняйте перед поездкой.',
    'Решите вопрос со страховкой','Отмена действующей zorgverzekering: до 31 декабря включительно. Новая: до 1 февраля. Сохраните подтверждения.',
    'Kerstvakantie Zuid: с 25.12 до 09.01.2028. Закладывайте время на праздничные поездки.')}

CHECKS=[]
class Design:
    def __init__(self,path,bleed=False):
        self.b=3 if bleed else 0
        self.c=canvas.Canvas(str(path),pagesize=((W+2*self.b)*MM,(H+2*self.b)*MM),pageCompression=1)
        self.c.setTitle('Nederland 2027 | Podslushano.nl | Новый дизайн')
        self.c.setAuthor('Podslushano.nl')
        self.c.setSubject('Горизонтальный настенный календарь. Дизайн-макет, регион Zuid.')
    def start(self):
        self.c.saveState(); self.c.translate(self.b*MM,self.b*MM)
        self.rect(-self.b,-self.b,W+2*self.b,H+2*self.b,'#FFFFFF')
    def end(self):self.c.restoreState(); self.c.showPage()
    def finish(self):self.c.save()
    def rect(self,x,y,w,h,color,stroke=None,lw=.2):
        self.c.setFillColor(HexColor(color));self.c.setLineWidth(lw*MM)
        if stroke:self.c.setStrokeColor(HexColor(stroke))
        self.c.rect(x*MM,(H-y-h)*MM,w*MM,h*MM,fill=1,stroke=int(bool(stroke)))
    def line(self,x1,y1,x2,y2,color=LINE,lw=.15):
        self.c.setStrokeColor(HexColor(color));self.c.setLineWidth(lw*MM)
        self.c.line(x1*MM,(H-y1)*MM,x2*MM,(H-y2)*MM)
    def txt(self,x,y,s,size=9,font='Onest400',color=INK,align='left'):
        self.c.setFont(font,size);self.c.setFillColor(HexColor(color))
        xx=x*MM;yy=(H-y)*MM-size*.82
        if align=='right':self.c.drawRightString(xx,yy,str(s))
        elif align=='center':self.c.drawCentredString(xx,yy,str(s))
        else:self.c.drawString(xx,yy,str(s))
    def lines(self,s,w,size,font):
        result=[]
        for para in str(s).split('\n'):
            line=''
            for word in para.split():
                candidate=(line+' '+word).strip()
                if pdfmetrics.stringWidth(candidate,font,size)<=w*MM:
                    line=candidate
                else:
                    if line:result.append(line)
                    line=word
                    # Exact word retained, typographic breaks when unavoidable.
                    while pdfmetrics.stringWidth(line,font,size)>w*MM:
                        n=len(line)-1
                        while pdfmetrics.stringWidth(line[:n]+'-',font,size)>w*MM:n-=1
                        result.append(line[:n]+'-');line=line[n:]
            result.append(line)
        return result
    def para(self,x,y,w,s,size=8.3,font='Onest400',color=INK,leading=None):
        leading=leading or size*.45
        lines=self.lines(s,w,size,font)
        for line in lines:self.txt(x,y,line,size,font,color);y+=leading
        return y
    def photo(self,name,x,y,w,h,anchor=.5):
        # Native photo cropped to the frame; no generative alteration.
        im=Image.open(ASSETS/name);iw,ih=im.size
        scale=max(w/iw,h/ih);dw,dh=iw*scale,ih*scale
        self.c.saveState();p=self.c.beginPath();p.rect(x*MM,(H-y-h)*MM,w*MM,h*MM);self.c.clipPath(p,stroke=0)
        self.c.drawImage(str(ASSETS/name),(x-(dw-w)*anchor)*MM,(H-y-h-(dh-h)*.5)*MM,dw*MM,dh*MM)
        self.c.restoreState()
    def brand(self,x,y,size=10):
        self.rect(x,y+.8,2,2,ORANGE)
        self.txt(x+4,y,'Podslushano.nl',size,'Onest600')
    def footer(self,n):
        self.line(13,199,284,199)
        self.txt(13,202,'NEDERLAND 2027',6.8,'Onest600',MUT)
        self.txt(148.5,202,'Podslushano.nl',7.1,'Onest500',INK,'center')
        self.txt(284,202,f'{n:02d} / 12',6.8,'Rubik400',MUT,'right')

def cover(d):
    d.start()
    d.brand(13,27,12)
    d.txt(284,28,'КАЛЕНДАРЬ ЭМИГРАНТА',8.3,'Onest500',INK,'right')
    d.line(13,38,284,38,INK,.23)
    d.txt(11.5,47,'Nederland',57,'Onest500')
    d.txt(11,75,'2027',110,'Rubik500')
    d.rect(15,121,16,1.6,ORANGE)
    d.para(14,133,108,'Год в Нидерландах.\nВажные даты — под рукой.',15,'Onest400',INK,6.6)
    d.para(14,155,105,'Праздники и каникулы.\nСезоны и места для прогулок.\nНапоминания о важном.',9.4,'Onest400',MUT,5)
    d.line(14,185,119,185)
    d.txt(14,189,'Личная версия',8.5,'Onest600')
    d.txt(14,195,'Образец: schoolvakanties Zuid',7.5,'Onest400',MUT)
    d.photo('photo_cover.jpg',133,49,151,144,.55)
    d.txt(133,196,'Amsterdam',7.5,'Onest500',MUT)
    d.txt(284,196,'52 недели для своих планов',7.5,'Onest400',MUT,'right')
    d.end()

def holiday_segments(week,m):
    a=[]
    for i,day in enumerate(week):
        if day.month!=m:continue
        for v in VAC:
            if v['start']<=day.isoformat()<=v['end']:
                if a and a[-1][1]==i-1 and a[-1][2]==v['name']:a[-1][1]=i
                else:a.append([i,i,v['name']])
    return a

def month(d,m):
    d.start()
    theme,place,season,go,tiptitle,tip,note=CONTENT[m]
    d.rect(13,27,10,10,ORANGE)
    d.txt(18,29.1,f'{m:02d}',16,'Rubik500',INK,'center')
    d.txt(27,24.8,DATA['months'][m-1],36,'Onest500')
    d.txt(27,40,NL[m-1]+'  /  '+theme,8.3,'Onest400',MUT)
    d.txt(284,24.5,'2027',32,'Rubik400',INK,'right')
    d.txt(284,39.8,'Каникулы: Zuid',8,'Onest400',MUT,'right')
    d.line(13,49,284,49,INK,.24)

    # Narrow editorial rail leaves more than 70% of the body for planning.
    d.photo(f'photo_{m}.jpg',13,56,57,44)
    d.txt(13,102.5,place,6.7,'Onest500',MUT)
    d.txt(13,111,'СЕЗОН',6.8,'Onest600',DARKORANGE)
    y=d.para(13,115.2,57,season,8.3,leading=3.55)
    d.txt(13,y+3.3,'КУДА ПОЕХАТЬ',6.8,'Onest600',DARKORANGE)
    y=d.para(13,y+7.5,57,go,8.3,leading=3.55)
    d.line(13,y+4,70,y+4)
    d.txt(13,y+7,'НА ЗАМЕТКУ',6.8,'Onest600',MUT)
    y=d.para(13,y+11.3,57,note,7.6,color=MUT,leading=3.25)
    ty=max(165,y+5)
    d.rect(13,ty,1.0,28.5,ORANGE)
    d.txt(17,ty,'СОВЕТ МЕСЯЦА',6.8,'Onest600',DARKORANGE)
    end=d.para(17,ty+4.5,53,tiptitle,9.2,'Onest600',leading=3.9)
    end=d.para(17,end+2,53,tip,7.8,leading=3.35)
    CHECKS.append({'type':'sidebar','month':m,'bottom':round(end,2),'limit':196.5})

    gx,gy,gw,gh=81,63,203,130
    cw=gw/7;weeks=calendar.Calendar(0).monthdatescalendar(2027,m);rh=gh/len(weeks)
    wd=['ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС'];wdnl=['ma','di','wo','do','vr','za','zo']
    d.txt(76.9,57.5,'НЕД.',5.1,'Onest500',MUT,'right')
    for col in range(7):
        if col>=5:d.rect(gx+col*cw,54.8,cw,138.2,SOFT)
        d.txt(gx+col*cw+2,56.5,wd[col],9.2,'Onest600')
        d.txt(gx+(col+1)*cw-2,57.0,wdnl[col],7.3,'Onest400',MUT,'right')
    colors={'hol':DARKORANGE,'dead':RED,'me':PINK,'bday':DARKORANGE,'oth':MUT,'dst':INK,'trad':INK}
    order={'me':0,'hol':1,'dead':2,'bday':3,'dst':4,'trad':5,'oth':6}
    for r,week in enumerate(weeks):
        yy=gy+r*rh
        d.txt(77,yy+2.7,f'{week[0].isocalendar().week:02d}',6.3,'Rubik400',MUT,'right')
        seg=holiday_segments(week,m)
        for col,day in enumerate(week):
            xx=gx+col*cw
            if day.month!=m:continue
            evs=sorted(EVENTS.get((m,day.day),[]),key=lambda e:order[e['kind']])
            holiday=any(e['kind']=='hol' for e in evs)
            personal=any(e['kind']=='me' for e in evs)
            if holiday:d.rect(xx,yy,cw,rh,PEACH)
            if personal:d.rect(xx,yy,cw,.65,PINK)
            d.txt(xx+2,yy+1.7,str(day.day),21 if len(weeks)<6 else 19,'Rubik400',DARKORANGE if holiday else INK)
            hasvac=any(a<=col<=b for a,b,_ in seg)
            fs=7.4 if len(weeks)<6 else 7.15
            lead=2.95 if len(weeks)<6 else 2.75
            ey=yy+(11 if len(weeks)<6 else 9.5)
            for e in evs:
                # Per-event metrics catch dense cells before delivery.
                f='Onest500' if e['kind'] in ['hol','dead','me'] else 'Onest400'
                ey=d.para(xx+2,ey,cw-4,e['label'],fs,f,colors[e['kind']],lead)
                ey+=.4
            limit=yy+rh-(3.8 if hasvac else 1)
            if evs:CHECKS.append({'type':'cell','month':m,'day':day.day,'bottom':round(ey-.4,2),'limit':round(limit,2)})
        for a,b,name in seg:
            bx=gx+a*cw+1.1;bw=(b-a+1)*cw-2.2
            d.rect(bx,yy+rh-3.55,bw,2.65,GREEN)
            label=f'{name} · Zuid' if bw>48 else 'Zuid'
            d.txt(bx+1.1,yy+rh-3.1,label,5.9,'Onest500',GREENTEXT)
    for i in range(8):d.line(gx+i*cw,gy,gx+i*cw,gy+gh,LINE,.12)
    for r in range(len(weeks)+1):d.line(gx,gy+r*rh,gx+gw,gy+r*rh,INK if r==0 else LINE,.22 if r==0 else .14)
    d.txt(81,195.1,'Полосы: schoolvakanties Zuid. Сверяйтесь с календарём своей школы.',6.15,'Onest400',MUT)
    d.footer(m);d.end()

def mini(d,m,x,y,w=40,h=28):
    d.txt(x,y,DATA['months'][m-1],9,'Onest600')
    cw=w/7;rs=3.25
    for j,s in enumerate(['П','В','С','Ч','П','С','В']):d.txt(x+(j+.5)*cw,y+5,s,5.8,'Onest500',MUT,'center')
    for i,week in enumerate(calendar.Calendar().monthdayscalendar(2027,m)):
        for j,day in enumerate(week):
            if not day:continue
            color=DARKORANGE if any(e['kind']=='hol' for e in EVENTS.get((m,day),[])) else (MUT if j>4 else INK)
            d.txt(x+(j+.5)*cw,y+8.8+i*rs,day,7.3,'Rubik400',color,'center')

def back(d):
    d.start()
    d.txt(12.2,26,'Год целиком',28,'Onest500')
    d.txt(284,26,'2027',32,'Rubik400',INK,'right')
    d.line(13,42,284,42,INK,.25)
    for m in range(1,13):mini(d,m,13+((m-1)%6)*46,49+((m-1)//6)*34,40)
    d.line(13,117,284,117)
    d.txt(13,123,'Как читать календарь',12,'Onest600')
    legends=[(PEACH,DARKORANGE,'27','Официальный праздник'),('#FFFFFF',RED,'Aa','Срок или действие'),('#FFFFFF',INK,'Aa','Событие или традиция'),('#FFFFFF',MUT,'Aa','Другие памятные даты'),('#FFFFFF',PINK,'Aa','Ваша личная дата'),(GREEN,GREENTEXT,'','Schoolvakanties Zuid')]
    for i,(bg,co,s,label) in enumerate(legends):
        yy=131+i*5.4;d.rect(13,yy,7,4,bg);d.txt(16.5,yy+.35,s,8,'Onest500',co,'center');d.txt(23,yy+.35,label,7.5)
    d.para(13,165,76,'Праздник не гарантирует выходной: проверьте CAO или трудовой договор. * Дата по ежегодному правилу, ждём анонс.',6.7,color=MUT,leading=2.9)

    x=104
    d.txt(x,123,'Платежи и документы',12,'Onest600')
    rows=[('Aangifte за 2026','Срок из aangiftebrief; обычно до 1 мая.'),
          ('Zorgverzekering','Отмена до 31.12; новая до 01.02.'),
          ('Gemeente и waterschap','Даты и рассрочка указаны в aanslag.'),
          ('Toeslagen и kinderbijslag','Проверьте даты в Mijn toeslagen / Mijn SVB.')]
    yy=132
    for title,body in rows:
        d.txt(x,yy,title,8.2,'Onest600');yy=d.para(x,yy+4.1,88,body,7.2,color=MUT,leading=3)+3

    qx=211
    d.txt(qx,123,'И в телефоне',12,'Onest600')
    widget=qr.QrCodeWidget('https://t.me/podslushano_nl_bot',barLevel='M',barBorder=4)
    bounds=widget.getBounds();sz=25*MM; drawing=Drawing(sz,sz,transform=[sz/(bounds[2]-bounds[0]),0,0,sz/(bounds[3]-bounds[1]),0,0]);drawing.add(widget)
    renderPDF.draw(drawing,d.c,qx*MM,(H-157)*MM)
    d.para(qx+29,133,44,'Бот\nPodslushano.nl\n\nНаведите камеру',7.2,leading=3.2)
    d.para(qx,161,73,'В образце QR открывает бота. В заказе здесь будет личный код календаря для подключения дат и напоминаний.',6.9,color=MUT,leading=3)
    d.line(13,182,284,182)
    d.para(13,185,271,'Источники дат: Rijksoverheid, Belastingdienst и сайты организаторов; дополнительные памятные даты — данные проекта. События могут меняться. Макет от 14.10.2026; перед тиражом нужна финальная сверка программ.',6.0,color=MUT,leading=2.65)
    credits='Фото: Wikimedia Commons, кадрирование. Обложка и январь: Nan Palmero (CC BY 2.0); февраль: Tobias Niepel (CC BY 2.0); март: acediscovery (CC BY 4.0); апрель: Roel Hemkes (CC BY 2.0); май, июль, декабрь: DimiTalen (CC0); июнь: Mykyta Nikiforov (CC BY 2.0); август: Gouwenaar (CC0); сентябрь: Paulswagerman (CC BY 4.0); октябрь: Rob Dammers (CC BY 2.0); ноябрь: Andy Li (CC0).'
    d.para(13,192,271,credits,5.65,color=MUT,leading=2.5)
    d.end()

def create(path,bleed=False):
    d=Design(path,bleed);cover(d)
    for m in range(1,13):month(d,m)
    back(d);d.finish()
    if bleed:
        r=PdfReader(path);w=PdfWriter()
        for p in r.pages:
            p.trimbox=RectangleObject([3*MM,3*MM,300*MM,213*MM])
            p.bleedbox=RectangleObject([0,0,303*MM,216*MM]);w.add_page(p)
        w.add_metadata({'/Title':'Nederland 2027 | Дизайн-макет с вылетами 3 мм','/Author':'Podslushano.nl'})
        with open(path,'wb') as f:w.write(f)

if __name__=='__main__':
    create(OUT/'Nederland-2027-new-design.pdf')
    create(OUT/'Nederland-2027-bleed-3mm.pdf',True)
    violations=[x for x in CHECKS if x['bottom']>x['limit']]
    (OUT/'layout-checks.json').write_text(json.dumps({'checks':len(CHECKS),'violations':violations},ensure_ascii=False,indent=2))
    print(json.dumps({'checks':len(CHECKS),'violations':violations},ensure_ascii=False))
    doc=fitz.open(OUT/'Nederland-2027-new-design.pdf')
    for i in range(len(doc)):
        pix=doc[i].get_pixmap(matrix=fitz.Matrix(1.65,1.65),alpha=False)
        pix.save(OUT/f'page-{i+1:02d}.png')
    print('Rendered',len(doc),'pages')
