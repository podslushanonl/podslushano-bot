# -*- coding: utf-8 -*-
"""Батч №3 (мост A1→A2): перфект и модальные конструкции.
- причастия — рукописная таблица (сильные глаголы наизусть);
- русское прошедшее: -ть → -л(а), исключения вручную.
Выход: data/sentences_batch3.json; +20 Q&A уровня A2 → дописываются в data/qa_pairs.json"""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bank=json.load(open(ROOT+'/data/bank.json',encoding='utf-8'))['themes']

# причастия (вручную, только проверенные)
PART={'zwemmen':'gezwommen','lezen':'gelezen','schrijven':'geschreven','werken':'gewerkt',
 'spelen':'gespeeld','koken':'gekookt','zingen':'gezongen','dansen':'gedanst','leren':'geleerd',
 'slapen':'geslapen','wandelen':'gewandeld','fietsen':'gefietst','sporten':'gesport',
 'voetballen':'gevoetbald','eten':'gegeten','drinken':'gedronken','betalen':'betaald',
 'helpen':'geholpen','luisteren':'geluisterd','praten':'gepraat','spreken':'gesproken',
 'reizen':'gereisd','tekenen':'getekend','studeren':'gestudeerd','bellen':'gebeld','vragen':'gevraagd'}
RU_PAST_EXC={'есть':'ел(а)','помочь':'помог(ла)'}
def ru_past(inf):
    inf=inf.split(' / ')[0].strip()
    if inf in RU_PAST_EXC:return RU_PAST_EXC[inf]
    parts=inf.split(' ')
    w=parts[0]
    if w.endswith('ться'):w=w[:-4]+'лся(ась)'
    elif w.endswith('ть'):w=w[:-2]+'л(а)'
    return ' '.join([w]+parts[1:])
def ru_past_pl(inf):
    p=ru_past(inf)
    p=p.replace('л(а)','ли').replace('лся(ась)','лись')
    return p
SOCIAL={'zwemmen','dansen','eten','koken','wandelen','fietsen','voetballen','spelen','zingen','sporten'}

# глагол → (ru, theme) из банка
verbs={}
for ti,th in enumerate(bank):
    for disp,ru in th['w']:
        if not disp.startswith(('de ','het ')) and disp.endswith('en') and ' ' not in disp:
            verbs.setdefault(disp,(ru,ti))

items=[];seen=set()
def add(nl,ru,lemma,theme):
    if nl in seen:return
    seen.add(nl);items.append({'nl':nl,'ru':ru,'lemma':lemma,'theme':theme})

MAG_OK={'bellen','vragen','lezen','luisteren','betalen','eten','drinken','spelen','zwemmen'}
for v,(ru,ti) in verbs.items():
    if v not in PART:continue           # только проверенные глаголы
    inf=ru.split(' / ')[0].strip()
    p=PART[v]
    # перфект
    add('Ik heb gisteren '+('lekker ' if v in SOCIAL else '')+p+'.','Вчера я '+ru_past(inf)+'.',v,ti)
    add('Heb je al '+p+'?','Ты уже '+ru_past(inf)+'?',v,ti)
    add('We hebben samen '+p+'.','Мы вместе '+ru_past_pl(inf)+'.',v,ti)
    add('Ik heb vandaag nog niet '+p+'.','Сегодня я ещё не '+ru_past(inf)+'.',v,ti)
    # модальные
    add('Ik moet vandaag '+v+'.','Сегодня мне нужно '+inf+'.',v,ti)
    add('Ik kan morgen niet '+v+'.','Завтра я не могу '+inf+'.',v,ti)
    if v in MAG_OK:
        add('Mag ik even '+v+'?','Можно мне '+inf+'?',v,ti)
    if v in SOCIAL:
        add('Wil je met mij '+v+'?','Хочешь со мной '+inf+'?',v,ti)
        add('Zullen we samen '+v+'?','Давай вместе '+inf+'?',v,ti)

json.dump({'note':'Батч №3: перфект (hebben + причастие) и модальные конструкции (moeten/kunnen/mogen/willen/zullen) на глаголы банка. Мост A1→A2.',
 'count':len(items),'items':items},
 open(ROOT+'/data/sentences_batch3.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("batch3:",len(items))

# ---- +20 Q&A (A2: работа, мнения, договорённости) ----
qa=json.load(open(ROOT+'/data/qa_pairs.json',encoding='utf-8'))
NEW=[
 ['Wat voor werk doe je?','Кем ты работаешь?','Ik werk in een restaurant.','Я работаю в ресторане.',1],
 ['Wat heb je gisteren gedaan?','Что ты делал(а) вчера?','Ik heb gewerkt en gekookt.','Я работал(а) и готовил(а).',1],
 ['Heb je goed geslapen?','Ты хорошо спал(а)?','Ja, heel goed, dank je.','Да, очень хорошо, спасибо.',1],
 ['Kun je me helpen?','Ты можешь мне помочь?','Ja, natuurlijk. Wat is er?','Да, конечно. Что случилось?',0],
 ['Mag ik hier zitten?','Можно мне здесь сесть?','Ja, ga je gang.','Да, пожалуйста.',0],
 ['Wil je iets drinken?','Хочешь что-нибудь выпить?','Ja, een thee graag.','Да, чай, пожалуйста.',3],
 ['Heb je al gegeten?','Ты уже поел(а)?','Nee, nog niet. Ik heb honger!','Нет, ещё нет. Я голоден (голодна)!',3],
 ['Moet je morgen werken?','Тебе завтра работать?','Ja, van negen tot vijf.','Да, с девяти до пяти.',1],
 ['Waarom leer je Nederlands?','Почему ты учишь нидерландский?','Voor mijn werk en het inburgeringsexamen.','Для работы и экзамена по интеграции.',2],
 ['Hoe lang woon je al in Nederland?','Как давно ты живёшь в Нидерландах?','Al twee jaar.','Уже два года.',0],
 ['Vind je Nederland leuk?','Тебе нравятся Нидерланды?','Ja, maar het regent veel!','Да, но часто идёт дождь!',7],
 ['Wat vind je van het eten hier?','Как тебе здешняя еда?','Lekker, vooral de kaas.','Вкусно, особенно сыр.',3],
 ['Kun je dat langzamer zeggen?','Можешь сказать это медленнее?','Ja, sorry. Ik praat te snel.','Да, извини. Я говорю слишком быстро.',2],
 ['Zullen we vrijdag afspreken?','Договоримся на пятницу?','Ja, vrijdag kan ik.','Да, в пятницу я могу.',1],
 ['Waar werk je?','Где ты работаешь?','Bij een groot bedrijf in de stad.','В большой компании в городе.',1],
 ['Heb je de bus gemist?','Ты опоздал(а) на автобус?','Ja, ik was te laat.','Да, я опоздал(а).',6],
 ['Wat ga je in het weekend doen?','Что будешь делать в выходные?','Ik ga naar het strand.','Поеду на пляж.',7],
 ['Ben je moe?','Ты устал(а)?','Ja, ik heb veel gewerkt.','Да, я много работал(а).',4],
 ['Kan de dokter vandaag komen?','Врач может прийти сегодня?','Nee, morgen om tien uur.','Нет, завтра в десять.',4],
 ['Mag ik met de kaart betalen?','Можно оплатить картой?','Ja, dat kan.','Да, можно.',5],
]
have={p['q_nl'] for p in qa['pairs']}
added=0
for a,b,c,dd,t in NEW:
    if a not in have:
        qa['pairs'].append({'q_nl':a,'q_ru':b,'a_nl':c,'a_ru':dd,'theme':t});added+=1
qa['count']=len(qa['pairs'])
json.dump(qa,open(ROOT+'/data/qa_pairs.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("qa added:",added,"total:",qa['count'])
