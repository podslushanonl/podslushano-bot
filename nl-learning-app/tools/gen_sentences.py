# -*- coding: utf-8 -*-
"""Батч №1: генерация естественных предложений A1 на слова банка.
Морфология RU (род/вин.падеж/мн.ч.) — правила + словари исключений (как в вычитке).
Шаблоны тематические и типизированные: предмет / человек / место / животное / глагол / прилагательное.
Выход: data/sentences_batch1.json  [{nl, ru, lemma, theme}]"""
import json,os,re
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bank=json.load(open(ROOT+'/data/bank.json',encoding='utf-8'))['themes']
vet=json.load(open(ROOT+'/data/vetted_translations.json',encoding='utf-8'))['items']
PLUV={v['lemma']:v for v in vet if v['type']=='noun_plural' and v['quality']=='correct'}
OLD_NL={v['nl'] for v in vet if v['type'] in ('sentence','question_sentence')}

# ---------- русская морфология (совместимо с вычиткой) ----------
VEL='гкхжчшщ'
OVR={'гостиная':('f','гостиные','гостиную'),'примерочная':('f','примерочные','примерочную'),
 'животное':('n','животные','животное'),'мороженое':('n','мороженое','мороженое'),
 'учащийся курса':('m','учащиеся курса','учащегося курса'),'Нидерланды':('p','Нидерланды','Нидерланды'),
 'люди':('p','люди','людей'),'обувь':('f','обувь','обувь'),'молоко':('n','молоко','молоко'),
 'имя':('n','имена','имя'),'время':('n','времена','время'),'солнце':('n','солнца','солнце'),
 'ухо':('n','уши','ухо'),'яблоко':('n','яблоки','яблоко'),'колено':('n','колени','колено'),
 'плечо':('n','плечи','плечо'),'цветная капуста':('f','цветная капуста','цветную капусту')}
UNCNT={'жильё','виноград','клубника','кожа','картофель','интернет','одежда','пиво','природа','рис','сахар','масло','мясо','лук','лимонад','музыка','морковь','вода','кофе','чай','хлеб','сыр','суп','колбаса','салат','погода'}
INDECL={'радио':'n','фото':'n','резюме':'n','метро':'n','кафе':'n','евро':'m','кофе':'m','хобби':'n'}
MASC_A={'мужчина','дедушка','дядя','коллега'}
MASC_SOFT={'зять','учитель','водитель','пекарь','словарь','путь','картофель','отель','дождь','пароль','преподаватель','работодатель','родитель','день','гость'}
ANIM_M={'мужчина','муж','брат','сын','отец','дедушка','дядя','друг','врач','водитель','продавец','преподаватель','учитель','стоматолог','сосед','коллега','клиент','менеджер','партнёр','пекарь','мясник','работник','сотрудник','работодатель','ребёнок','мальчик','младенец','человек','внук','зять','племянник','свёкор','родитель','гость'}
FEM_PERS={'женщина','подруга','учительница','ассистентка','соседка','девочка','бабушка','мать','дочь','сестра','жена','невестка','тётя','племянница','свекровь'}
ANIMALS={'собака','кошка','лошадь','корова','свинья','овца','курица','птица','животное','рыба'}
PLACES={'школа','аптека','больница','супермаркет','рынок','вокзал','музей','парк','кафе','ресторан','магазин','офис','бассейн','кемпинг','отель','станция','центр','деревня','город','пляж','сад','кухня','спальня','ванная','гостиная','туалет','班'}
PL_EXC={'человек':'люди','ребёнок':'дети','брат':'братья','стул':'стулья','друг':'друзья','дерево':'деревья','сын':'сыновья','муж':'мужья','дочь':'дочери','мать':'матери','глаз':'глаза','дом':'дома','город':'города','поезд':'поезда','адрес':'адреса','лес':'леса','остров':'острова','номер':'номера','цветок':'цветы','сосед':'соседи','сестра':'сёстры','жена':'жёны','отец':'отцы','рот':'рты','ветер':'ветры','снег':'снега','хлеб':'хлеба','зять':'зятья','свёкор':'свёкры','путь':'пути','учитель':'учителя','палец':'пальцы','счёт':'счета','отпуск':'отпуска','время':'времена','имя':'имена'}
OK_DICT={'звонок':'звонки','замок':'замки','носок':'носки','подбородок':'подбородки','рынок':'рынки','сок':'соки','восток':'востоки','урок':'уроки','заголовок':'заголовки','перекрёсток':'перекрёстки'}
ACC_EXC={'отец':'отца','ребёнок':'ребёнка','зять':'зятя','свёкор':'свёкра','продавец':'продавца','младенец':'младенца'}
VERB_OK={'zwemmen','lezen','schrijven','werken','spelen','koken','zingen','dansen','leren','slapen','wandelen','fietsen','sporten','voetballen','eten','drinken','betalen','helpen','luisteren','praten','spreken','reizen','tekenen','studeren','bellen','vragen','kijken?'}-{'kijken?'}
DRINKS={'кофе','чай','молоко','вода','вино','пиво','сок','лимонад'}
ABSTRACT={'боль','вопрос','ответ','проблема','язык','имя','время','задание','урок','правило','предложение','номер','адрес','цена','размер','штраф','счёт','запись','поездка','работа','профессия','сумма','километр','зарплата','аренда','движение','отпуск','перерыв','встреча','дата','пароль','сообщение','музыка','погода','интернет','буква','слово','текст','страница','кожа','песня','совещание','собеседование','обед','ужин','завтрак','матч','концерт','фильм','игра','хобби','спорт','утро','вечер','ночь','день','неделя','месяц','год','секунда','минута','час','выходные','вид','сорт','количество','точка','кружок','крестик','черта','линия','половина','пауза','смысл'}
WEAR={'куртка','брюки','обувь','носок','свитер','платье','юбка','очки','рубашка','футболка','шапка','шарф','перчатка','сапог','майка','трусы','пальто','кардиган','жилет','блузка','костюм','шляпа','пачка','туфля','джинсы','ремень','галстук','кофта'}
ADJ_SKIP={'злой','сердитый','больной','женатый','голодный','усталый','сытый','живой','старый','молодой','мёртвый','радостный','испуганный','довольный','весёлый','грустный','счастливый','занятой','оживлённый','свободный','целый','следующий','последний','первый'}
NEED_SKIP={'страна','сторона','провинция','север','юг','запад','восток','остров','деревня','город','лес','море','пляж','природа','погода','солнце','ветер','дождь','снег','облако','тело','лицо','семья','человек','люди','зубы','волосы'}
FOOD_SKIP={'пачка','пакет','литр','грамм','кило','килограмм','фунт','марка','касса','чек','рынок','супермаркет','магазин','кухня','ложка','вилка','нож','тарелка','стакан','чашка','кастрюля','духовка','холодильник','стол','обед','ужин','завтрак','вид','сорт','половина','продавец','пекарь','мясник','бутылка','банка','счёт','цена','деньги'}
BODY={'голова','рука','нога','спина','глаз','ухо','нос','рот','живот','горло','колено','плечо','шея','палец','зуб','ступня','кисть','губа','подбородок','щека','лицо','волосы','борода','усы','мышца'}
COLORS={'синий','красный','жёлтый','зелёный','белый','чёрный','серый','коричневый','оранжевый','розовый','фиолетовый','голубой'}
ADJ_ADV_MAP={'хороший':'хорошо','горячий':'горячо','свежий':'свежо'}
ADJ_END=('ый','ий','ой','ая','яя','ое','ее','ые','ие')
def is_adj(t):return t.endswith(ADJ_END) and len(t)>4
def gender_of(h):
    if h in INDECL:return INDECL[h]
    if h in ('время','имя'):return 'n'
    if h in MASC_A or h in MASC_SOFT:return 'm'
    if h.endswith(('ы','и')):return 'p'
    if h.endswith(('а','я')):return 'f'
    if h.endswith(('о','е','ё')):return 'n'
    if h.endswith('ь'):return 'f'
    return 'm'
def plural_noun(h):
    if h in INDECL or h in UNCNT:return h
    if h in PL_EXC:return PL_EXC[h]
    if h in OK_DICT:return OK_DICT[h]
    if h.endswith(('ы','и')) and gender_of(h)=='p':return h
    if h.endswith('ия'):return h[:-1]+'и'
    if h.endswith('а'):return h[:-1]+('и' if h[-2] in VEL else 'ы')
    if h.endswith('я'):return h[:-1]+'и'
    if h.endswith(('ь','й')):return h[:-1]+'и'
    if h.endswith('о'):return h[:-1]+'а'
    if h.endswith('ие'):return h[:-1]+'я'
    if h.endswith('е'):return h[:-1]+'я'
    if h.endswith('ец') and len(h)>4:return h[:-2]+'цы'
    return h+('и' if h[-1] in VEL else 'ы')
def acc_noun(h,g,anim):
    if h in INDECL:return h
    if h in ACC_EXC:return ACC_EXC[h]
    if g=='f':
        if h.endswith('а'):return h[:-1]+'у'
        if h.endswith('я'):return h[:-1]+'ю'
        return h
    if g=='m' and anim:
        if h.endswith('а'):return h[:-1]+'у'
        if h.endswith('я'):return h[:-1]+'ю'
        if h.endswith(('ь','й')):return h[:-1]+'я'
        return h+'а'
    if g=='p' and anim:return 'людей' if h=='люди' else h
    return h
def adj_pl(a):
    for e,r in (('ая','ие' if a[-3] in VEL else 'ые'),('яя','ие'),('ый','ые'),('ий','ие'),('ой','ые'),('ое','ые'),('ее','ие')):
        if a.endswith(e):return a[:-2]+r
    return a
def adj_acc_f(a):
    if a.endswith('ая'):return a[:-2]+'ую'
    if a.endswith('яя'):return a[:-2]+'юю'
    return a
def adj_acc_manim(a):
    if a.endswith(('ый','ой')):return a[:-2]+'ого'
    if a.endswith('ий'):return a[:-2]+'его'
    return a
def parse_ru(ru):
    ru0=ru.split(' / ')[0].strip()
    if ru0 in OVR:
        g,pl,ac=OVR[ru0]
        h=ru0.split()[0]
        return {'n':ru0,'g':g,'pl':pl,'a':ac,'head':h,'anim':(h in ANIM_M)or(h in FEM_PERS)or(h in ANIMALS)or ru0 in('люди','дети','животное')}
    toks=ru0.split()
    hi=next((i for i,t in enumerate(toks) if not is_adj(t)),len(toks)-1)
    h=toks[hi];g=gender_of(h)
    anim=(h in ANIM_M)or(h in FEM_PERS)or(h in ANIMALS)or h in('люди','дети')
    plt=[adj_pl(t) if i<hi else (plural_noun(t) if i==hi else t) for i,t in enumerate(toks)]
    if g=='f':act=[adj_acc_f(t) if i<hi else (acc_noun(t,g,anim) if i==hi else t) for i,t in enumerate(toks)]
    elif g=='m' and anim:act=[adj_acc_manim(t) if i<hi else (acc_noun(t,g,anim) if i==hi else t) for i,t in enumerate(toks)]
    else:act=[t if i<hi else (acc_noun(t,g,anim) if i==hi else t) for i,t in enumerate(toks)]
    return {'n':ru0,'g':g,'pl':' '.join(plt),'a':' '.join(act),'head':h,'anim':anim}
def gsel(g,m,f,n,p=None):
    return {'m':m,'f':f,'n':n,'p':(p if p is not None else m)}[g]
def adj_adv(ru):
    r=ru.split(' / ')[0].strip()
    if r in ADJ_ADV_MAP:return ADJ_ADV_MAP[r]
    if r.endswith(('ый','ой')):return r[:-2]+'о'
    return None
VEL_TUPLE=tuple(VEL)

def kind_of(disp,ru,ty):
    if ty=='verb_infinitive':return 'verb'
    if ty in ('adjective_or_adverb','color'):return 'adj'
    p=parse_ru(ru)
    h=p['head']
    if h in PLACES:return 'place'
    if p['anim'] and h in ANIMALS:return 'animal'
    if p['anim']:return 'person'
    return 'obj'

def cap(s):return s[:1].upper()+s[1:]
def bare(disp):
    return re.sub(r'^(de|het|een)\s+','',disp)

# ---------- шаблоны: (nl, ru) с функциями подстановки ----------
def frames_for(theme_i,kind,disp,ru,lemma):
    P=parse_ru(ru);D=disp;B=bare(disp);g=P['g']
    countable=lemma in PLUV
    out=[]
    def add(nl,r):
        out.append((nl,r))
    if kind=='obj':
        head=P['head']
        visible=countable and head not in ABSTRACT and head not in BODY and P['head'] not in UNCNT
        if head in DRINKS:
            add('Ik drink graag '+B+'.','Я люблю пить '+P['a']+'.')
            add('Wil je '+B+'?','Хочешь '+P['a']+'?')
            add(cap(D)+' is lekker.',cap(P['n'])+' — '+gsel(g,'вкусный','вкусная','вкусное','вкусные')+'.')
            add('Ik neem '+B+', alstublieft.','Мне '+P['a']+', пожалуйста.')
        if head not in ABSTRACT:
            add('Waar is '+D+'?','Где '+P['n']+'?')
            add('Is dit '+D+'?','Это '+P['n']+'?')
        if visible:
            add(cap(D)+' is hier, denk ik.',cap(P['n'])+' здесь, я думаю.')
            add('Ik zie '+D+' niet.','Я не вижу '+P['a']+'.')
        if head not in ABSTRACT and head not in BODY and head not in NEED_SKIP:
            add('Ik heb '+('een '+B if visible else D)+' nodig.','Мне '+gsel(g,'нужен','нужна','нужно','нужны')+' '+P['n']+'.')
        if theme_i==3 and head not in DRINKS and head not in FOOD_SKIP:  # еда
            add(cap(D)+' is lekker.',cap(P['n'])+' — '+gsel(g,'вкусный','вкусная','вкусное','вкусные')+'.')
            add('Ik koop '+D+' in de supermarkt.','Я покупаю '+P['a']+' в супермаркете.')
            if head in UNCNT or not countable:
                eatnl=(PLUV[lemma]['nl'].split(' ')[-1] if lemma in PLUV else B)
                add('Ik eet graag '+eatnl+'.','Я люблю есть '+P['a']+'.')
                add('Wil je '+B+'?','Хочешь '+P['a']+'?')
            else:
                plb=PLUV[lemma]['nl'].split(' ')[-1]
                add('Ik eet graag '+plb+'.','Я люблю есть '+P['pl']+'.')
                add('Wil je een '+B+'?','Хочешь '+P['a']+'?')
        if theme_i==4 and head in BODY:
            add('Mijn '+B+' doet pijn.','У меня болит '+P['n']+'.')
            add('Doet je '+B+' pijn?','У тебя болит '+P['n']+'?')
        if theme_i==5 and head in WEAR:  # одежда (только носимое)
            add(cap(D)+' past goed.',cap(P['n'])+' хорошо сидит.')
            add('Ik draag vandaag '+('een ' if visible else '')+B+'.','Сегодня на мне '+P['n']+'.')
            add('Heeft u deze '+B+' in maat 40?','У вас есть '+P['n']+' сорокового размера?')
        if theme_i==6 and head in {'поезд','автобус','трамвай','самолёт','велосипед','машина','лодка','метро'}:
            add(cap(D)+' vertrekt om negen uur.',cap(P['n'])+' отправляется в девять часов.')
            add('Ik wacht op '+D+'.','Я жду '+P['a']+'.')
        if theme_i==7 and head not in ABSTRACT:
            add('Ik vind '+D+' leuk.','Мне нравится '+P['n']+'.')
    elif kind=='place':
        add('Ik ga naar '+D+'.','Я иду в '+P['a']+'.' if P['head'] not in {'рынок','вокзал','пляж','стадион'} else 'Я иду на '+P['a']+'.')
        add('Waar is '+D+'?','Где '+P['n']+'?')
        add(cap(D)+' is vandaag dicht.',cap(P['n'])+' сегодня закрыт.' if g=='m' else (cap(P['n'])+' сегодня закрыта.' if g=='f' else cap(P['n'])+' сегодня закрыто.'))
        add(cap(D)+' is om de hoek.',cap(P['n'])+' за углом.')
        add('Is '+D+' ver?','До '+P['n']+' далеко?' if False else ('Далеко ли '+P['n']+'?'))
    elif kind=='person':
        add(cap(D)+' is erg aardig.',cap(P['n'])+' очень '+gsel(g,'приятный','приятная','приятное','приятные')+'.')
        add('Ik ken '+D+' goed.','Я хорошо знаю '+P['a']+'.')
        add('Daar loopt '+D+'.','Вон идёт '+P['n']+'.')
        add(cap(D)+' helpt mij vaak.',cap(P['n'])+' часто мне помогает.' if g!='p' else cap(P['n'])+' часто мне помогают.')
        add('Ken jij '+D+'?','Ты знаешь '+P['a']+'?')
    elif kind=='animal':
        add(cap(D)+' speelt in de tuin.',cap(P['n'])+' играет в саду.' if g!='p' else cap(P['n'])+' играют в саду.')
        add('Kijk, '+D+'!','Смотри, '+P['n']+'!')
        add('Ik heb thuis '+('een ' if countable else '')+B+'.','У меня дома '+P['n']+'.')
        add('Is '+D+' groot?',cap(P['n'])+' '+gsel(g,'большой','большая','большое','большие')+'?')
    elif kind=='verb':
        if B not in VERB_OK:return out
        inf=ru.split(' / ')[0].strip()
        add('Ik wil graag '+B+'.','Я очень хочу '+inf+'.')
        add('We gaan morgen '+B+'.','Завтра мы будем '+inf+'.')
        add('Ik kan goed '+B+'.','Я хорошо умею '+inf+'.')
        add('Vandaag ga ik niet '+B+'.','Сегодня я не буду '+inf+'.')
    elif kind=='adj':
        r0=ru.split(' / ')[0].strip()
        if r0 in COLORS:
            add('Het is '+B+'.','Это '+r0+' цвет.')
            add('Ik vind '+B+' mooi.','Мне нравится '+r0+' цвет.')
            add('Mijn jas is '+B+'.','Моя куртка — '+({'синий':'синяя','красный':'красная','жёлтый':'жёлтая','зелёный':'зелёная','белый':'белая','чёрный':'чёрная','серый':'серая','коричневый':'коричневая','оранжевый':'оранжевая','розовый':'розовая','фиолетовый':'фиолетовая','голубой':'голубая'}).get(r0,r0)+'.')
        else:
            if r0 in ADJ_SKIP:return out
            adv=adj_adv(ru)
            if not adv:return out
            add('Het is '+B+'.','Это '+adv+'.')
            add('Dat is heel '+B+'.','Это очень '+adv+'.')
            add('Is het '+B+'?','Это '+adv+'?')
    return out

def run_batch1():
    items=[];seen=set()
    _run(bank,items,seen,'sentences_batch1.json','Батч №1 предложений A1 (тематические шаблоны + русская морфология). Источник уроков и пула экзаменов.')
    return items

def _run(bank,items,seen,fname,note):
  for ti,th in enumerate(bank):
    for wi,(disp,ru) in enumerate(th['w']):
        # тип берём из bank? bank хранит только пары; восстановим тип по эвристике:
        ty='noun'
        if not disp.startswith(('de ','het ')):
            # глагол или прилагательное: глаголы инфинитив на -en; прилагательные — прочее
            ty='verb_infinitive' if disp.endswith('en') and ' ' not in disp else 'adjective_or_adverb'
        lemma=bare(disp)
        kind=kind_of(disp,ru,ty)
        frs=frames_for(ti,kind,disp,ru,lemma)
        # ротация: до 4 предложений на слово, начиная со сдвига по индексу
        take=[]
        for k in range(len(frs)):
            fr=frs[(wi+k)%len(frs)]
            if fr not in take:take.append(fr)
            if len(take)>=5:break
        for nl,r in take:
            if nl in OLD_NL or nl in seen:continue
            if '..' in r or '  ' in nl or '{' in nl+r:continue
            seen.add(nl)
            items.append({'nl':nl,'ru':r,'lemma':lemma,'theme':ti})
  print("generated:",len(items))
  json.dump({'note':note,'count':len(items),'items':items},
   open(ROOT+'/data/'+fname,'w',encoding='utf-8'),ensure_ascii=False,indent=1)

if __name__=='__main__':
    items=run_batch1()
    import random
    random.seed(7)
    for it in random.sample(items,min(45,len(items))):
        print(' ',it['nl'],'||',it['ru'])
