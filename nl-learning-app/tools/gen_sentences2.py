# -*- coding: utf-8 -*-
"""Батч №2:
1) предложения на слова ОФИЦИАЛЬНОГО словаря TaalCompleet A1 (674), которых не покрыл батч №1;
2) вопрос-ответные пары A1 (коммуникативное ядро инбургеринга).
Выход: data/sentences_batch2.json, data/qa_pairs.json"""
import json,os,sys
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec=importlib.util.spec_from_file_location('g1',os.path.join(os.path.dirname(os.path.abspath(__file__)),'gen_sentences.py'))
g1=importlib.util.module_from_spec(spec);spec.loader.exec_module(g1)
ROOT=g1.ROOT

wl=json.load(open(ROOT+'/data/taalcompleet_a1_woordenlijst.json',encoding='utf-8'))['words']
b1=json.load(open(ROOT+'/data/sentences_batch1.json',encoding='utf-8'))['items']
covered={it['lemma'] for it in b1}
old_nl={it['nl'] for it in b1}|g1.OLD_NL

# WL → структура «банка» по темам 1..8 → индексы 0..7
themes=[{'t':str(t),'w':[]} for t in range(8)]
for w in wl:
    lm=w['nl']
    if lm in covered:continue          # уже есть предложения из батча №1
    ru=w['ru']
    if ':' in ru or '(' in ru:continue
    pos=w.get('pos')
    if pos=='noun' and w.get('article'):
        disp=w['article']+' '+w['nl']
    elif pos=='verb':
        disp=w['nl']
        if not disp.endswith('en'):continue
    elif pos=='adj':
        disp=w['nl']
    else:
        continue                        # word/phrase — уже в словаре, фраз не строим
    themes[w['theme']-1]['w'].append([disp,ru])

# у WL есть свои множественные числа — дополняем PLUV данными словаря
for w in wl:
    if w.get('pos')=='noun' and w.get('plural') and w['nl'] not in g1.PLUV:
        pr=g1.parse_ru(w['ru'])
        g1.PLUV[w['nl']]={'nl':w['plural'],'ru':pr['pl']}

items=[];seen=set(old_nl)
g1._run(themes,items,seen,'sentences_batch2.json','Батч №2: предложения на слова официального словаря TaalCompleet A1 (не покрытые батчем №1).')

# ---------------- ВОПРОС-ОТВЕТНЫЕ ПАРЫ (ядро A1) ----------------
QA=[
 # знакомство
 ['Hoe heet je?','Как тебя зовут?','Ik heet Anna.','Меня зовут Анна.',0],
 ['Waar kom je vandaan?','Откуда ты?','Ik kom uit Rusland.','Я из России.',0],
 ['Waar woon je?','Где ты живёшь?','Ik woon in Amsterdam.','Я живу в Амстердаме.',0],
 ['Hoe oud ben je?','Сколько тебе лет?','Ik ben dertig jaar.','Мне тридцать лет.',0],
 ['Hoe gaat het met je?','Как у тебя дела?','Goed, dank je. En met jou?','Хорошо, спасибо. А у тебя?',0],
 ['Ben je getrouwd?','Ты женат / замужем?','Ja, ik ben getrouwd.','Да, я женат / замужем.',0],
 ['Heb je kinderen?','У тебя есть дети?','Ja, ik heb twee kinderen.','Да, у меня двое детей.',0],
 ['Heb je broers of zussen?','У тебя есть братья или сёстры?','Ik heb één broer en één zus.','У меня один брат и одна сестра.',0],
 ['Wat is je telefoonnummer?','Какой у тебя номер телефона?','Mijn nummer is nul zes, twaalf, veertien.','Мой номер — 06-12-14.',0],
 ['Spreek je Nederlands?','Ты говоришь по-нидерландски?','Ja, een beetje.','Да, немного.',0],
 ['Hoe schrijf je dat?','Как это пишется?','Zo: A-N-N-A.','Вот так: А-Н-Н-А.',0],
 ['Wat betekent dat?','Что это значит?','Dat betekent «дом».','Это значит «дом».',0],
 # каждый день / время
 ['Hoe laat is het?','Который час?','Het is half negen.','Половина девятого.',1],
 ['Wanneer sta je op?','Когда ты встаёшь?','Ik sta om zeven uur op.','Я встаю в семь часов.',1],
 ['Wat doe je vandaag?','Что ты сегодня делаешь?','Ik werk en daarna sport ik.','Я работаю, а потом занимаюсь спортом.',1],
 ['Welke dag is het vandaag?','Какой сегодня день?','Het is dinsdag.','Сегодня вторник.',1],
 ['Wat is de datum vandaag?','Какое сегодня число?','Het is tien juli.','Сегодня десятое июля.',1],
 ['Wanneer ben je jarig?','Когда у тебя день рождения?','Op vijf mei.','Пятого мая.',1],
 # школа
 ['Begrijp je de vraag?','Ты понимаешь вопрос?','Nee, kunt u het herhalen?','Нет, вы можете повторить?',2],
 ['Op welke bladzijde zijn we?','На какой мы странице?','Op bladzijde twaalf.','На странице двенадцать.',2],
 ['Wanneer is de les?','Когда урок?','Op maandag en donderdag.','В понедельник и четверг.',2],
 ['Mag ik iets vragen?','Можно спросить?','Ja, natuurlijk!','Да, конечно!',2],
 # еда
 ['Wat wil je drinken?','Что будешь пить?','Een koffie met melk, graag.','Кофе с молоком, пожалуйста.',3],
 ['Hoeveel kost het?','Сколько это стоит?','Drie euro vijftig.','Три евро пятьдесят.',3],
 ['Anders nog iets?','Что-нибудь ещё?','Nee, dank u. Dat was het.','Нет, спасибо. Это всё.',3],
 ['Wat eten we vanavond?','Что мы едим сегодня вечером?','We eten soep met brood.','Мы едим суп с хлебом.',3],
 ['Mag ik de rekening?','Можно счёт?','Ja, ik kom eraan.','Да, сейчас подойду.',3],
 ['Wilt u pinnen of contant?','Картой или наличными?','Pinnen, graag.','Картой, пожалуйста.',3],
 # здоровье
 ['Wat zijn uw klachten?','На что жалуетесь?','Ik heb hoofdpijn en koorts.','У меня болит голова и температура.',4],
 ['Sinds wanneer bent u ziek?','С какого времени вы болеете?','Sinds maandag.','С понедельника.',4],
 ['Hoe vaak per dag?','Сколько раз в день?','Drie keer per dag, na het eten.','Три раза в день, после еды.',4],
 ['Wilt u een afspraak maken?','Хотите записаться на приём?','Ja, graag. Kan het morgen?','Да, пожалуйста. Можно завтра?',4],
 # одежда / покупки
 ['Welke maat heeft u?','Какой у вас размер?','Maat achtendertig.','Размер тридцать восемь.',5],
 ['Mag ik dit passen?','Можно это примерить?','Ja, de paskamer is daar.','Да, примерочная там.',5],
 ['Hoe laat sluit de winkel?','Во сколько закрывается магазин?','Om zes uur.','В шесть часов.',5],
 ['Heeft u dit in het blauw?','У вас есть это в синем?','Ik kijk even voor u.','Сейчас посмотрю для вас.',5],
 # путешествия
 ['Hoe laat gaat de trein?','Во сколько идёт поезд?','Om tien over negen.','В девять десять.',6],
 ['Van welk spoor vertrekt de trein?','С какого пути отправляется поезд?','Van spoor vijf.','С пятого пути.',6],
 ['Waar is de bushalte?','Где автобусная остановка?','Om de hoek, bij de supermarkt.','За углом, у супермаркета.',6],
 ['Is het ver lopen?','Далеко идти пешком?','Nee, tien minuten.','Нет, десять минут.',6],
 ['Mag ik een kaartje naar Utrecht?','Можно билет до Утрехта?','Ja, dat is negen euro.','Да, это девять евро.',6],
 # досуг
 ['Wat doe je in je vrije tijd?','Что ты делаешь в свободное время?','Ik zwem en ik lees.','Я плаваю и читаю.',7],
 ['Ga je mee naar de film?','Пойдёшь со мной в кино?','Ja, leuk! Hoe laat?','Да, здорово! Во сколько?',7],
 ['Wat is je hobby?','Какое у тебя хобби?','Mijn hobby is koken.','Моё хобби — готовить.',7],
 ['Heb je een huisdier?','У тебя есть домашнее животное?','Ja, ik heb een kat.','Да, у меня кошка.',7],
 ['Wat voor weer is het?','Какая погода?','De zon schijnt!','Светит солнце!',7],
]
qa=[{'q_nl':a,'q_ru':b,'a_nl':c,'a_ru':d,'theme':t} for a,b,c,d,t in QA]
json.dump({'note':'Вопрос-ответные пары A1 (коммуникативное ядро). Используются в уроках: «Что ответить на …?» + аудирование вопроса.','count':len(qa),'pairs':qa},
 open(ROOT+'/data/qa_pairs.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("qa pairs:",len(qa))
