# -*- coding: utf-8 -*-
"""Батч №4: предложения на A2-лексику (темы 11–13: чувства/дом-переезд/официальные дела).
- чувства: ik ben/was + adj (имперфект was — новинка A2);
- мнения: Ik vind … belangrijk;
- новые причастия (verhuisd, ingevuld, ondertekend);
- официальные конструкции (aanvragen, afspraak bij de gemeente).
Выход: data/sentences_batch4.json (+10 Q&A A2)."""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bank=json.load(open(ROOT+'/data/bank.json',encoding='utf-8'))['themes']

FEEL={'радостный':'рад(а)','сердитый':'сердит(а)','грустный':'грустен (грустна)','усталый':'устал(а)',
 'испуганный':'напуган(а)','гордый':'горд(а)','влюблённый':'влюблён (влюблена)','довольный':'доволен (довольна)'}
items=[];seen=set()
def add(nl,ru,lemma,theme):
    if nl in seen:return
    seen.add(nl);items.append({'nl':nl,'ru':ru,'lemma':lemma,'theme':theme})

# --- тема «Общение и чувства» (индекс 10): только проверенные слова ---
FEELING_OK={'blij':'рад(а)','boos':'сердит(а)','verdrietig':'грустен (грустна)','moe':'устал(а)',
 'bang':'напуган(а)','trots':'горд(а)','verliefd':'влюблён (влюблена)','tevreden':'доволен (довольна)'}
FEELING_FULL={'blij':'радостный','boos':'сердитый','verdrietig':'грустный','moe':'усталый',
 'bang':'испуганный','trots':'гордый','verliefd':'влюблённый','tevreden':'довольный'}
TRAIT_OK={'vriendelijk':'дружелюбный','eerlijk':'честный','gezellig':'душевный'}
for a,short in FEELING_OK.items():
    add('Ik ben vandaag een beetje '+a+'.','Сегодня я немного '+short+'.',a,10)
    add('Waarom ben je zo '+a+'?','Почему ты такой(ая) '+FEELING_FULL[a]+'?',a,10)
    add('Ik was gisteren erg '+a+'.','Вчера я был(а) очень '+short+'.',a,10)
for a,r in TRAIT_OK.items():
    add('Mijn collega is heel '+a+'.','Мой коллега очень '+r+'.',a,10)
COMM=[
 ('Wat is jouw mening?','Каково твоё мнение?','mening'),
 ('Dat is een goed idee!','Это хорошая идея!','idee'),
 ('Ik heb een beter plan.','У меня есть план получше.','plan'),
 ('Het was een leuk gesprek.','Это был приятный разговор.','gesprek'),
 ('Heb je het nieuws gehoord?','Ты слышал(а) новости?','nieuws'),
 ('Vertel je verhaal maar!','Ну, рассказывай свою историю!','verhaal'),
 ('Dat was een goede grap!','Это была хорошая шутка!','grap'),
 ('We hebben ruzie gehad, maar nu is alles goed.','Мы поссорились, но теперь всё хорошо.','ruzie'),
 ('Wat een mooi compliment!','Какой приятный комплимент!','compliment'),
 ('De keuze is aan jou.','Выбор за тобой.','keuze'),
 ('Ik heb een droom: een eigen huis.','У меня есть мечта — собственный дом.','droom'),
 ('Belangrijk is dat je het probeert.','Важно то, что ты пытаешься.','belangrijk'),
]
for nl,ru,lm in COMM:add(nl,ru,lm,10)

# --- тема «Дом и переезд» (индекс 11): перфект переезда ---
MOVE=[
 ('Ik ben vorige maand verhuisd.','В прошлом месяце я переехал(а).','verhuizen'),
 ('Wij zijn naar Utrecht verhuisd.','Мы переехали в Утрехт.','verhuizen'),
 ('Heb je de dozen al ingepakt?','Ты уже упаковал(а) коробки?','doos'),
 ('De buren hebben ons geholpen.','Соседи нам помогли.','buren'),
 ('Ik heb het huurcontract gelezen en ondertekend.','Я прочитал(а) и подписал(а) договор аренды.','huurcontract'),
 ('De borg is één maand huur.','Залог — месячная аренда.','borg'),
 ('Wanneer is de bezichtiging?','Когда просмотр жилья?','bezichtiging'),
 ('We hebben de muren geschilderd.','Мы покрасили стены.','schilderen'),
 ('De verwarming doet het niet.','Отопление не работает.','verwarming'),
 ('Waar zet ik de container neer?','Куда мне поставить контейнер?','container'),
 ('Het afval gaat op dinsdag buiten.','Мусор выносят по вторникам.','afval'),
 ('De verhuiswagen komt om negen uur.','Грузовик для переезда приедет в девять.','verhuiswagen'),
 ('Ik heb nieuwe buren. Ze zijn aardig!','У меня новые соседи. Они приятные!','buren'),
 ('De stroom en het gas zijn geregeld.','Электричество и газ подключены.','stroom'),
 ('Mijn huisgenoot kookt vandaag.','Мой сосед по квартире сегодня готовит.','huisgenoot'),
]
for nl,ru,lm in MOVE:add(nl,ru,lm,11)

# --- тема «Официальные дела» (индекс 12) ---
OFF=[
 ('Ik heb een afspraak bij de gemeente.','У меня приём в муниципалитете.','gemeente'),
 ('Waar kan ik een uittreksel aanvragen?','Где я могу запросить выписку?','uittreksel'),
 ('U kunt de vergunning online aanvragen.','Вы можете запросить разрешение онлайн.','vergunning'),
 ('Heeft u uw identiteitskaart bij u?','У вас с собой удостоверение личности?','identiteitskaart'),
 ('Ik heb het formulier al ingevuld.','Я уже заполнил(а) формуляр.','invullen'),
 ('Wilt u hier ondertekenen?','Распишитесь здесь, пожалуйста.','ondertekenen'),
 ('De wachtrij is lang vandaag.','Очередь сегодня длинная.','wachtrij'),
 ('Ga naar loket drie, alstublieft.','Пройдите к третьему окну, пожалуйста.','loket'),
 ('Ik heb een kopie van mijn paspoort nodig.','Мне нужна копия паспорта.','kopie'),
 ('De toeslag komt volgende week.','Субсидия придёт на следующей неделе.','toeslag'),
 ('Mijn verblijfsvergunning is nog geldig.','Мой вид на жительство ещё действителен.','verblijfsvergunning'),
 ('Ik heb een brief van de belastingdienst gekregen.','Я получил(а) письмо из налоговой.','belastingdienst'),
 ('U krijgt binnen twee weken een melding.','Вы получите уведомление в течение двух недель.','melding'),
 ('Het pakket ligt bij de buren.','Посылка у соседей.','pakket'),
 ('De termijn is al voorbij.','Срок уже прошёл.','termijn'),
 ('Dit document is gratis.','Этот документ бесплатный.','document'),
 ('Ik wil bezwaar maken.','Я хочу подать возражение.','bezwaar'),
 ('De zorgverzekering is verplicht in Nederland.','Медицинская страховка в Нидерландах обязательна.','zorgverzekering'),
]
for nl,ru,lm in OFF:add(nl,ru,lm,12)

json.dump({'note':'Батч №4: A2-конструкции — чувства (ik ben/was + adj), мнения (ik vind … belangrijk), переезд и официальные дела (перфект: verhuisd/ingevuld/ondertekend).',
 'count':len(items),'items':items},
 open(ROOT+'/data/sentences_batch4.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("batch4:",len(items))

# --- +10 Q&A A2 ---
qa=json.load(open(ROOT+'/data/qa_pairs.json',encoding='utf-8'))
NEW=[
 ['Waarom ben je verhuisd?','Почему ты переехал(а)?','Mijn oude huis was te klein.','Моя старая квартира была слишком маленькой.',11],
 ['Heeft u een afspraak?','У вас назначен приём?','Ja, om half elf.','Да, на полодиннадцатого.',12],
 ['Wat is er gebeurd?','Что случилось?','Niets ergs. Alles is oké.','Ничего страшного. Всё в порядке.',10],
 ['Waarom ben je zo blij?','Почему ты такой радостный (такая радостная)?','Ik heb een nieuwe baan!','У меня новая работа!',10],
 ['Hoe was je weekend?','Как прошли выходные?','Heel gezellig, dank je.','Очень душевно, спасибо.',10],
 ['Welke documenten moet ik meenemen?','Какие документы мне взять с собой?','Uw paspoort en een kopie.','Ваш паспорт и копию.',12],
 ['Wanneer komt de verhuiswagen?','Когда приедет грузовик для переезда?','Zaterdag om negen uur.','В субботу в девять.',11],
 ['Ben je boos op mij?','Ты на меня сердишься?','Nee hoor, het geeft niet.','Да нет, всё нормально.',10],
 ['Hoe lang duurt de aanvraag?','Сколько длится оформление заявки?','Ongeveer twee weken.','Примерно две недели.',12],
 ['Bevalt het nieuwe huis?','Нравится новое жильё?','Ja, vooral de grote keuken!','Да, особенно большая кухня!',11],
]
have={p['q_nl'] for p in qa['pairs']}
added=0
for a,b,c,dd,t in NEW:
    if a not in have:
        qa['pairs'].append({'q_nl':a,'q_ru':b,'a_nl':c,'a_ru':dd,'theme':t});added+=1
qa['count']=len(qa['pairs'])
json.dump(qa,open(ROOT+'/data/qa_pairs.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("qa added:",added,"total:",qa['count'])
