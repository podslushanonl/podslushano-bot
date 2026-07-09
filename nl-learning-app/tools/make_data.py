# -*- coding: utf-8 -*-
"""Генерирует data/bank.json, data/lessons_generated.json, data/dialogues.json (чистый JSON)."""
import json
import os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
items=json.load(open(ROOT+"/data/dutch_a1_a2_5000.json",encoding='utf-8'))['items']

# ---- вычитанное ----
VETL={};POSSV={};DEMV={};PLUV={}
_vv=json.load(open(ROOT+"/data/vetted_translations.json",encoding='utf-8'))['items']
for v in _vv:
    if v['quality']!='correct': continue
    t=v['type'];lm=v['lemma'];rec={'nl':v['nl'],'ru':v['ru_vetted']}
    if t in ('sentence','question_sentence'):VETL.setdefault(lm,[]).append(rec)
    elif t=='possessive_phrase':POSSV.setdefault(lm,[]).append(rec)
    elif t=='demonstrative_phrase':DEMV.setdefault(lm,[]).append(rec)
    elif t=='noun_plural':PLUV[lm]=rec
def vet_pick(lemma,salt):
    lst=VETL.get(lemma)
    return lst[salt%len(lst)] if lst else None

CLEAN={'noun','verb_infinitive','adjective_or_adverb','color'}
EMOJI={'noun':'📦','verb_infinitive':'▶️','adjective_or_adverb':'🔤','color':'🎨'}
MAP=[('Знакомство',['people','family','greetings','pronouns','politeness']),
 ('Каждый день',['time','numbers','frequency','basic','smalltalk','feelings']),
 ('Школа',['school','classroom','work']),
 ('Еда и напитки',['food','drinks']),
 ('Здоровье',['health']),
 ('Одежда',['clothing','colors']),
 ('Путешествия',['travel','geography']),
 ('Досуг',['leisure','nature','weather','digital'])]
def disp_of(it):
    if it['type'] in ('noun','color') and it.get('article'):
        return (it['article']+' '+it['nl']).strip()
    return it['nl']
BANK=[]
for name,dts in MAP:
    seen=set();ws=[]
    for it in items:
        if it['theme'] in dts and it['type'] in CLEAN:
            d=disp_of(it);ru=it['ru'].strip()
            if not ru or d in seen:continue
            if ':' in ru or '(' in ru:continue
            seen.add(d);ws.append((d,ru,it['type']))
    BANK.append((name,ws))

def pick_distractors(pool,correct,key_idx,n=3,salt=0):
    out=[];i=salt;L=len(pool);g=0
    while len(out)<n and g<L*3:
        v=pool[i%L][key_idx]
        if v!=correct and v not in out:out.append(v)
        i+=1;g+=1
    while len(out)<n:out.append(correct)
    return out

lesson_num=39;meta=[];lessons={};themeLessons={}
for ti in range(2,8):
    name,ws=BANK[ti]
    chunks=[ws[i:i+8] for i in range(0,len(ws),8)]
    chunks=[c for c in chunks if len(c)>=4][:7]
    nums=[]
    for ci,chunk in enumerate(chunks):
        n=lesson_num;lesson_num+=1;nums.append(n)
        meta.append({'n':n,'t':'Слова: '+name.lower()+' '+str(ci+1),'blk':ti+1})
        half=(len(chunk)+1)//2
        p1=chunk[:half];p2=chunk[half:];pool=ws
        parts=[]
        # ---- ЧАСТЬ 1 ----
        steps=[{'t':'explain','k':'Новые слова','b':'📖 Слова темы','html':'<p>Новые слова темы «'+name+'». Нажимай ▶, слушай и запоминай — потом закрепим в заданиях.</p>'}]
        for d,ru,ty in p1:
            steps.append({'t':'word','k':'Слово','emoji':EMOJI.get(ty,'📌'),'nl':d,'tr':ru})
        for j,(d,ru,ty) in enumerate(p1[:2]):
            steps.append({'t':'quiz','k':'Выбор','q':'Как будет «'+ru+'»?','opts':[d]+pick_distractors(pool,d,0,3,salt=j+ci)})
        steps.append({'t':'match','k':'Пары','pairs':[[d,ru] for d,ru,ty in p1]})
        d0,ru0,ty0=p1[0]
        steps.append({'t':'listen','k':'Аудирование','audio':d0,'q':'Что прозвучало?','opts':[d0]+pick_distractors(pool,d0,0,3,salt=ci+5)})
        for d,ru,ty in p1:  # притяжательные
            lm=d.split(' ')[-1];pv=POSSV.get(lm)
            if pv and len(pv)+len(DEMV.get(lm,[]))>=3:
                v=pv[ci%len(pv)]
                distr=[x['nl'] for x in pv if x['nl']!=v['nl']][:3]
                if len(distr)<3 and DEMV.get(lm):
                    distr+=[x['nl'] for x in DEMV[lm] if x['nl'] not in distr][:3-len(distr)]
                steps.append({'t':'quiz','k':'Мой, твой…','q':'Как сказать «'+v['ru']+'»?','opts':[v['nl']]+distr[:3]})
                break
        ALL_NL=[x['nl'] for lst in VETL.values() for x in lst]
        for d,ru,ty in p1:  # аудирование предложения
            v=vet_pick(d.split(' ')[-1],ci)
            if v and len(ALL_NL)>=4:
                others=[x for x in ALL_NL if x!=v['nl']]
                sd=[];ii=ci*7+3
                for _ in range(len(others)):
                    cand=others[ii%len(others)];ii+=1
                    if cand not in sd:sd.append(cand)
                    if len(sd)>=3:break
                steps.append({'t':'listen','k':'Аудирование','audio':v['nl'],'q':'Какое предложение прозвучало?','opts':[v['nl']]+sd})
                break
        parts.append({'t':'Новые слова','steps':steps})
        # ---- ЧАСТЬ 2 ----
        steps=[{'t':'explain','k':'Ещё слова','b':'📖 Слова темы','html':'<p>Ещё несколько слов темы «'+name+'». Дальше — перевод и говорение.</p>'}]
        for d,ru,ty in p2:
            steps.append({'t':'word','k':'Слово','emoji':EMOJI.get(ty,'📌'),'nl':d,'tr':ru})
        for j,(d,ru,ty) in enumerate(p2[:2]):
            steps.append({'t':'quiz','k':'Значение','q':'«'+d+'» — это…','opts':[ru]+pick_distractors(pool,ru,1,3,salt=j+ci+2)})
        for d,ru,ty in p2[:2]:
            steps.append({'t':'translate','k':'Перевод','q':'«'+ru+'»','answer':[d],'ph':'…'})
        if p2:
            d,ru,ty=p2[0]
            wrong=pick_distractors(pool,ru,1,1,salt=ci+9)[0]
            steps.append({'t':'tf','k':'Верно?','q':'«'+d+'» значит «'+wrong+'».','answer':False,'note':'Нет: '+d+' — '+ru+'.'})
        for d,ru,ty in p2:  # пары этот/мой
            lm=d.split(' ')[-1]
            pairs=[[x['nl'],x['ru']] for x in DEMV.get(lm,[])[:2]]+[[x['nl'],x['ru']] for x in POSSV.get(lm,[])[:2]]
            if len(pairs)>=3:
                steps.append({'t':'match','k':'Этот, мой…','pairs':pairs[:4]})
                break
        for d,ru,ty in (p1+p2):  # мн. число
            lm=d.split(' ')[-1];pl=PLUV.get(lm)
            if pl:
                distr=[];pool_lms=[x[0].split(' ')[-1] for x in pool];ii=ci*5+1
                for _ in range(len(pool_lms)*2):
                    cand=PLUV.get(pool_lms[ii%len(pool_lms)]);ii+=1
                    if cand and cand['nl']!=pl['nl'] and cand['nl'] not in distr:distr.append(cand['nl'])
                    if len(distr)>=3:break
                if len(distr)>=2:
                    steps.append({'t':'quiz','k':'Мн. число','q':'Множественное число от «'+d+'» ('+ru+') — ?','opts':[pl['nl']]+distr[:3]})
                    break
        addedS=0
        for d,ru,ty in (p1+p2):  # предложения build
            lm=d.split(' ')[-1]
            v=vet_pick(lm,ci+addedS*2+1)
            if v and addedS<2:
                import re as _re
                toks=_re.sub(r'[.?!]$','',v['nl']).split(' ')
                steps.append({'t':'build','k':'Предложение','tr':v['ru'],'words':toks,'ans':toks})
                addedS+=1
        spk=None
        for d,ru,ty in (p2+p1):
            if d.startswith(('de ','het ','een ')):spk=(d,ru);break
        if spk:
            steps.append({'t':'speak','k':'Говорение','phrase':'Dit is '+spk[0]+'.','tr':'Это '+spk[1]+'.'})
        parts.append({'t':'Закрепление','steps':steps})
        lessons[str(n)]={'parts':parts}
    themeLessons[str(ti)]=nums

json.dump({'themes':[{'t':name,'w':[[d,ru] for d,ru,ty in ws]} for name,ws in BANK]},
 open(ROOT+'/data/bank.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
json.dump({'note':'Автоуроки тем 3–8 (39–79), сгенерированы make_data из банка 5000 + vetted_translations. Схема: meta[{n,t,blk}], themeLessons{ti:[n]}, lessons{n:{parts:[{t,steps[]}]}}.',
 'meta':meta,'themeLessons':themeLessons,'lessons':lessons},
 open(ROOT+'/data/lessons_generated.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("bank.json themes:",len(BANK),"| lessons:",len(lessons),"| meta:",len(meta))

# ================= ДИАЛОГИ (14) =================
def dlg_html(lines):
    h='<div style="text-align:left">'
    for sp,nl,ru in lines:
        h+='<p style="margin:7px 0"><b>'+sp+':</b> '+nl+'<br><span style="color:var(--ink-2);font-size:12.5px">'+ru+'</span></p>'
    return h+'</div>'
def D(lesson,title,banner,lines,ex,listen,q1,q2,tf,build_tr,build_words,speak_nl,speak_ru):
    steps=[{'t':'explain','k':'Диалог','b':'💬 '+banner,'html':dlg_html(lines),'ex':ex},
     {'t':'listen','k':'Аудирование','audio':listen[0],'q':listen[1],'opts':listen[2]},
     {'t':'quiz','k':'Понимание','q':q1[0],'opts':q1[1]},
     {'t':'quiz','k':'Понимание','q':q2[0],'opts':q2[1]},
     {'t':'tf','k':'Верно?','q':tf[0],'answer':tf[1],'note':tf[2]},
     {'t':'build','k':'Собери','tr':build_tr,'words':build_words,'ans':build_words},
     {'t':'speak','k':'Говорение','phrase':speak_nl,'tr':speak_ru}]
    return {'lesson':lesson,'title':title,'steps':steps}

DLGS=[
 # ---- существующие 6 ----
 D(21,'Диалог: в классе','In de klas',
   [['Docent','Goedemorgen! Welkom in de klas.','Учитель: Доброе утро! Добро пожаловать в класс.'],
    ['Cursist','Goedemorgen, meneer!','Ученик: Доброе утро!'],
    ['Docent','Open het boek op bladzijde tien.','Учитель: Откройте книгу на странице десять.'],
    ['Cursist','Sorry, wat zegt u?','Ученик: Извините, что вы сказали?'],
    ['Docent','Bladzijde tien. En pak je pen.','Учитель: Страница десять. И возьми ручку.']],
   [['Welkom in de klas','Добро пожаловать в класс'],['Sorry, wat zegt u?','Извините, что вы сказали?']],
   ['Open het boek op bladzijde tien','Что сказал учитель?',['Open het boek op bladzijde tien','Open de deur, alsjeblieft','Pak je pen en papier','Welkom in de klas']],
   ['На какой странице нужно открыть книгу?',['на десятой','на пятой','на двадцатой','на третьей']],
   ['Что учитель просит взять?',['ручку','карандаш','бумагу','ластик']],
   ['Ученик понял учителя с первого раза.',False,'Нет — он переспросил: «Sorry, wat zegt u?»'],
   'Откройте книгу.',['Open','het','boek'],'Sorry, wat zegt u?','Извините, что вы сказали?'),
 D(24,'Диалог: на рынке','Op de markt',
   [['Verkoper','Goedemiddag! Zegt u het maar.','Продавец: Добрый день! Слушаю вас.'],
    ['Klant','Ik wil graag een kilo appels.','Покупатель: Мне, пожалуйста, килограмм яблок.'],
    ['Verkoper','Anders nog iets?','Продавец: Что-нибудь ещё?'],
    ['Klant','Ja, twee bananen. Hoeveel kost het?','Покупатель: Да, два банана. Сколько это стоит?'],
    ['Verkoper','Drie euro vijftig.','Продавец: Три евро пятьдесят.']],
   [['Anders nog iets?','Что-нибудь ещё?'],['Hoeveel kost het?','Сколько это стоит?']],
   ['Hoeveel kost het','Что спросил покупатель?',['Hoeveel kost het?','Anders nog iets?','Waar is de markt?','Wat wilt u?']],
   ['Что покупает клиент?',['яблоки и бананы','хлеб и сыр','молоко','виноград']],
   ['Сколько стоит покупка?',['3,50 €','2,50 €','5,00 €','1,50 €']],
   ['Клиент купил только яблоки.',False,'Нет — ещё два банана.'],
   'Мне, пожалуйста, килограмм яблок.',['Ik','wil','graag','een','kilo','appels'],'Hoeveel kost het?','Сколько это стоит?'),
 D(27,'Диалог: у врача','Bij de dokter',
   [['Dokter','Goedemorgen. Wat zijn uw klachten?','Врач: Доброе утро. На что жалуетесь?'],
    ['Patiënt','Ik heb hoofdpijn en koorts.','Пациент: У меня болит голова и температура.'],
    ['Dokter','Sinds wanneer bent u ziek?','Врач: С какого времени вы болеете?'],
    ['Patiënt','Sinds maandag.','Пациент: С понедельника.'],
    ['Dokter','Ik geef u een recept voor de apotheek.','Врач: Я дам вам рецепт для аптеки.']],
   [['Wat zijn uw klachten?','На что жалуетесь?'],['Ik heb hoofdpijn','У меня болит голова']],
   ['Ik heb hoofdpijn en koorts','Что сказал пациент?',['Ik heb hoofdpijn en koorts','Ik ben niet ziek','Mijn been doet pijn','Ik heb een afspraak']],
   ['Что болит у пациента?',['голова','нога','спина','зуб']],
   ['С какого дня пациент болеет?',['с понедельника','со вторника','с пятницы','с субботы']],
   ['Врач дал рецепт для аптеки.',True,'Да: een recept voor de apotheek.'],
   'У меня температура.',['Ik','heb','koorts'],'Ik heb hoofdpijn en koorts.','У меня болит голова и температура.'),
 D(30,'Диалог: в магазине','In de winkel',
   [['Klant','Mag ik deze broek passen?','Покупатель: Можно примерить эти брюки?'],
    ['Medewerker','Ja, natuurlijk. De paskamer is daar.','Продавец: Да, конечно. Примерочная — там.'],
    ['Klant','Welke maat is dit?','Покупатель: Какой это размер?'],
    ['Medewerker','Maat 38.','Продавец: Размер 38.'],
    ['Klant','De broek past goed. Ik neem hem!','Покупатель: Брюки хорошо сидят. Беру!']],
   [['Mag ik deze broek passen?','Можно примерить эти брюки?'],['De paskamer is daar','Примерочная — там']],
   ['Mag ik deze broek passen','Что спросил покупатель?',['Mag ik deze broek passen?','Waar is de kassa?','Hoeveel kost de jas?','Welke maat is dit?']],
   ['Что примеряет покупатель?',['брюки','куртку','платье','обувь']],
   ['Какой размер?',['38','36','40','42']],
   ['Брюки не подошли покупателю.',False,'Подошли: «De broek past goed».'],
   'Можно примерить эти брюки?',['Mag','ik','deze','broek','passen'],'Waar is de paskamer?','Где примерочная?'),
 D(33,'Диалог: на вокзале','Op het station',
   [['Reiziger','Pardon, hoe laat gaat de trein naar Utrecht?','Путешественник: Извините, во сколько поезд на Утрехт?'],
    ['Medewerker','Om tien uur, van spoor vijf.','Сотрудник: В десять часов, с пятого пути.'],
    ['Reiziger','Wat kost een kaartje?','Путешественник: Сколько стоит билет?'],
    ['Medewerker','Negen euro.','Сотрудник: Девять евро.'],
    ['Reiziger','Dank u wel!','Путешественник: Большое спасибо!']],
   [['Hoe laat gaat de trein?','Во сколько идёт поезд?'],['Wat kost een kaartje?','Сколько стоит билет?']],
   ['Hoe laat gaat de trein naar Utrecht','Что спросил путешественник?',['Hoe laat gaat de trein naar Utrecht?','Waar is de bushalte?','Mag ik hier zitten?','Waar is het station?']],
   ['Куда едет путешественник?',['в Утрехт','в Амстердам','в Роттердам','в Гаагу']],
   ['Во сколько идёт поезд?',['в 10:00','в 9:00','в 5:00','в 12:00']],
   ['Билет стоит девять евро.',True,'Да: negen euro.'],
   'Во сколько идёт поезд?',['Hoe','laat','gaat','de','trein'],'Eén kaartje naar Utrecht, alstublieft.','Один билет до Утрехта, пожалуйста.'),
 D(36,'Диалог: свободное время','Vrije tijd',
   [['Anna','Wat doe je in je vrije tijd?','Анна: Что ты делаешь в свободное время?'],
    ['Tom','Ik zwem en ik speel voetbal. En jij?','Том: Я плаваю и играю в футбол. А ты?'],
    ['Anna','Ik luister naar muziek en ik lees.','Анна: Я слушаю музыку и читаю.'],
    ['Tom','Ga je zaterdag mee naar het strand?','Том: Пойдёшь в субботу со мной на пляж?'],
    ['Anna','Ja, leuk! Tot zaterdag!','Анна: Да, здорово! До субботы!']],
   [['Wat doe je in je vrije tijd?','Что ты делаешь в свободное время?'],['Ga je mee?','Пойдёшь со мной?']],
   ['Wat doe je in je vrije tijd','Что спросила Анна?',['Wat doe je in je vrije tijd?','Waar woon je?','Hoe gaat het met je?','Wat eet je vandaag?']],
   ['Что делает Том в свободное время?',['плавает и играет в футбол','читает книги','танцует','поёт']],
   ['Куда они пойдут в субботу?',['на пляж','в кино','в парк','в музей']],
   ['Анна слушает музыку и читает.',True,'Да, так она и сказала.'],
   'Я плаваю и играю в футбол.',['Ik','zwem','en','ik','speel','voetbal'],'Wat doe je in je vrije tijd?','Что ты делаешь в свободное время?'),
 # ---- новые 8 ----
 D(2,'Диалог: знакомство','Kennismaken',
   [['Anna','Hallo! Ik ben Anna. Hoe heet jij?','Анна: Привет! Я Анна. Как тебя зовут?'],
    ['Tom','Hoi! Mijn naam is Tom.','Том: Привет! Меня зовут Том.'],
    ['Anna','Waar kom je vandaan, Tom?','Анна: Откуда ты, Том?'],
    ['Tom','Ik kom uit Rusland. En jij?','Том: Я из России. А ты?'],
    ['Anna','Ik woon in Amsterdam.','Анна: Я живу в Амстердаме.']],
   [['Hoe heet jij?','Как тебя зовут?'],['Waar kom je vandaan?','Откуда ты?']],
   ['Waar kom je vandaan','Что спросила Анна?',['Waar kom je vandaan?','Hoe gaat het?','Hoe oud ben je?','Waar woon je?']],
   ['Как зовут девушку?',['Анна','Мария','Ольга','Эмма']],
   ['Откуда Том?',['из России','из Нидерландов','из Германии','из Бельгии']],
   ['Анна живёт в Амстердаме.',True,'Да: «Ik woon in Amsterdam».'],
   'Я из России.',['Ik','kom','uit','Rusland'],'Hallo! Ik ben Anna.','Привет! Я Анна.'),
 D(13,'Диалог: который час','Hoe laat is het?',
   [['Sara','Hoe laat is het?','Сара: Который час?'],
    ['Omar','Het is acht uur.','Омар: Восемь часов.'],
    ['Sara','O nee, ik ben laat! De les begint om negen uur.','Сара: О нет, я опаздываю! Урок начинается в девять.'],
    ['Omar','Rustig! Je hebt nog een uur.','Омар: Спокойно! У тебя ещё час.'],
    ['Sara','Ja, je hebt gelijk.','Сара: Да, ты прав.']],
   [['Hoe laat is het?','Который час?'],['De les begint om negen uur','Урок начинается в девять']],
   ['Het is acht uur','Что ответил Омар?',['Het is acht uur','Het is negen uur','Het is tien uur','Het is één uur']],
   ['Сколько сейчас времени?',['восемь часов','девять часов','десять часов','семь часов']],
   ['Во сколько начинается урок?',['в девять','в восемь','в десять','в одиннадцать']],
   ['Сара уже опоздала на урок.',False,'Нет — у неё ещё целый час.'],
   'Который час?',['Hoe','laat','is','het'],'Hoe laat is het?','Который час?'),
 D(22,'Диалог: расписание','De agenda',
   [['Lisa','Welke dag is het vandaag?','Лиза: Какой сегодня день?'],
    ['Ali','Het is woensdag.','Али: Среда.'],
    ['Lisa','En wanneer is de les Nederlands?','Лиза: А когда урок нидерландского?'],
    ['Ali','Op maandag en donderdag.','Али: В понедельник и четверг.'],
    ['Lisa','Dank je wel!','Лиза: Спасибо!']],
   [['Welke dag is het vandaag?','Какой сегодня день?'],['op maandag en donderdag','в понедельник и четверг']],
   ['Het is woensdag','Что ответил Али?',['Het is woensdag','Het is maandag','Het is vrijdag','Het is zondag']],
   ['Какой сегодня день?',['среда','понедельник','пятница','воскресенье']],
   ['Когда уроки нидерландского?',['в понедельник и четверг','во вторник и пятницу','в среду и субботу','каждый день']],
   ['Урок нидерландского бывает по средам.',False,'Нет — по понедельникам и четвергам.'],
   'Какой сегодня день?',['Welke','dag','is','het','vandaag'],'Welke dag is het vandaag?','Какой сегодня день?'),
 D(25,'Диалог: ужин дома','Het avondeten',
   [['Mila','Wat eten we vanavond?','Мила: Что мы едим сегодня вечером?'],
    ['Daan','Ik kook soep met brood.','Дан: Я готовлю суп с хлебом.'],
    ['Mila','Lekker! Heb je hulp nodig?','Мила: Вкусно! Тебе нужна помощь?'],
    ['Daan','Ja, graag. Snijd jij de ui?','Дан: Да, пожалуйста. Порежешь лук?'],
    ['Mila','Oké, geen probleem.','Мила: Окей, без проблем.']],
   [['Wat eten we vanavond?','Что мы едим сегодня вечером?'],['Heb je hulp nodig?','Тебе нужна помощь?']],
   ['Ik kook soep met brood','Что сказал Дан?',['Ik kook soep met brood','Ik eet een appel','Ik drink koffie','Ik koop brood']],
   ['Что готовят на ужин?',['суп с хлебом','рыбу с рисом','салат','яичницу']],
   ['О чём Дан просит Милу?',['порезать лук','купить хлеб','помыть посуду','накрыть на стол']],
   ['Мила отказалась помогать.',False,'Нет — она согласилась: «Oké, geen probleem».'],
   'Я готовлю суп.',['Ik','kook','soep'],'Wat eten we vanavond?','Что мы едим сегодня вечером?'),
 D(28,'Диалог: в аптеке','Bij de apotheek',
   [['Klant','Goedemiddag, ik heb een recept.','Клиент: Добрый день, у меня рецепт.'],
    ['Apotheker','Dank u. Een moment, alstublieft.','Аптекарь: Спасибо. Минутку, пожалуйста.'],
    ['Apotheker','Dit medicijn is drie keer per dag.','Аптекарь: Это лекарство — три раза в день.'],
    ['Klant','Voor of na het eten?','Клиент: До или после еды?'],
    ['Apotheker','Na het eten, met water.','Аптекарь: После еды, с водой.']],
   [['Ik heb een recept','У меня рецепт'],['drie keer per dag','три раза в день']],
   ['Dit medicijn is drie keer per dag','Что сказал аптекарь?',['Dit medicijn is drie keer per dag','De apotheek is dicht','Wij hebben geen medicijnen','Het recept is oud']],
   ['Сколько раз в день принимать лекарство?',['три раза','один раз','два раза','четыре раза']],
   ['Как принимать лекарство?',['после еды, с водой','до еды','только утром','перед сном']],
   ['Лекарство принимают до еды.',False,'Нет — после еды (na het eten).'],
   'У меня рецепт.',['Ik','heb','een','recept'],'Voor of na het eten?','До или после еды?'),
 D(31,'Диалог: покупка обуви','Schoenen kopen',
   [['Klant','Ik zoek schoenen, maat 42.','Покупатель: Я ищу обувь, размер 42.'],
    ['Medewerker','Deze zijn mooi. Wilt u ze passen?','Продавец: Вот красивые. Хотите примерить?'],
    ['Klant','Ja... Ze zijn te klein.','Покупатель: Да… Они малы.'],
    ['Medewerker','Hier is maat 43.','Продавец: Вот размер 43.'],
    ['Klant','Die passen goed. Ik neem ze!','Покупатель: Эти подходят. Беру!']],
   [['Ik zoek schoenen','Я ищу обувь'],['Ze zijn te klein','Они слишком малы']],
   ['Ze zijn te klein','Что сказал покупатель после примерки?',['Ze zijn te klein','Ze zijn te groot','Ze zijn mooi','Ze zijn duur']],
   ['Что ищет покупатель?',['обувь','куртку','брюки','шапку']],
   ['Какой размер подошёл?',['43','42','41','44']],
   ['Размер 42 подошёл сразу.',False,'Нет — 42 был мал, подошёл 43.'],
   'Я ищу обувь.',['Ik','zoek','schoenen'],'Wilt u ze passen?','Хотите их примерить?'),
 D(34,'Диалог: как пройти','De weg vragen',
   [['Toerist','Pardon, waar is het museum?','Турист: Извините, где музей?'],
    ['Vrouw','Ga rechtdoor en dan linksaf.','Женщина: Идите прямо, потом налево.'],
    ['Toerist','Is het ver?','Турист: Это далеко?'],
    ['Vrouw','Nee, tien minuten lopen.','Женщина: Нет, десять минут пешком.'],
    ['Toerist','Dank u wel!','Турист: Большое спасибо!']],
   [['Waar is het museum?','Где музей?'],['Ga rechtdoor en dan linksaf','Идите прямо, потом налево']],
   ['Ga rechtdoor en dan linksaf','Как пройти к музею?',['Ga rechtdoor en dan linksaf','Ga naar rechts en dan rechtdoor','Neem de bus','Het is hier']],
   ['Что ищет турист?',['музей','вокзал','аптеку','рынок']],
   ['Сколько идти пешком?',['десять минут','пять минут','полчаса','час']],
   ['До музея нужно ехать на автобусе.',False,'Нет — десять минут пешком.'],
   'Идите прямо.',['Ga','rechtdoor'],'Pardon, waar is het museum?','Извините, где музей?'),
 D(37,'Диалог: домашние животные','Huisdieren',
   [['Emma','Heb jij een huisdier?','Эмма: У тебя есть домашнее животное?'],
    ['Lucas','Ja, ik heb een hond. Hij heet Max.','Лукас: Да, у меня собака. Его зовут Макс.'],
    ['Emma','Wat leuk! Is hij groot?','Эмма: Здорово! Он большой?'],
    ['Lucas','Nee, hij is klein en lief.','Лукас: Нет, он маленький и милый.'],
    ['Emma','Ik heb twee katten.','Эмма: А у меня две кошки.']],
   [['Heb jij een huisdier?','У тебя есть домашнее животное?'],['Hij is klein en lief','Он маленький и милый']],
   ['Ik heb een hond','Что сказал Лукас?',['Ik heb een hond','Ik heb een kat','Ik heb een paard','Ik heb geen huisdier']],
   ['Как зовут собаку?',['Макс','Том','Рекс','Лукас']],
   ['Сколько кошек у Эммы?',['две','одна','три','ни одной']],
   ['Собака Лукаса большая.',False,'Нет — маленькая и милая.'],
   'У меня собака.',['Ik','heb','een','hond'],'Heb jij een huisdier?','У тебя есть домашнее животное?'),
]
json.dump({'note':'Мини-диалоги с вопросами на понимание. Каждый добавляется частью «title» в урок «lesson».','count':len(DLGS),'dialogues':DLGS},
 open(ROOT+'/data/dialogues.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("dialogues:",len(DLGS),"→ data/dialogues.json")
