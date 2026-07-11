# -*- coding: utf-8 -*-
"""Генерирует data/grammar_b1.json — 6 грамматических блоков уровня B1.
Заголовки начинаются с «Грамматика» → на карте это отдельные узлы со значком 📐."""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def rule(rows):
    h='<div class="rule"><table style="width:100%;border-collapse:collapse">'
    for r in rows:
        h+='<tr>'+''.join('<td style="padding:4px 8px;border:1px solid var(--brd)"><b>'+c+'</b></td>' for c in r)+'</tr>'
    return h+'</table></div>'

parts=[
# 1) Пассив
{'title':'Грамматика: пассив (wordt gedaan) 🔄','theme':'Карьера','idx':2,'steps':[
 {'t':'explain','k':'Правило B1 · пассив','b':'🔄 Пассив: worden + voltooid deelwoord',
  'html':'<p>Пассив (lijdende vorm) нужен, когда важно <b>действие</b>, а не тот, кто его делает. Строится: <b>worden</b> + причастие (voltooid deelwoord) в конце.</p>'
   +rule([['Актив','De baas betaalt het loon.'],['Пассив','Het loon <b>wordt betaald</b>.'],['Кем? (door)','Het loon wordt <b>door de baas</b> betaald.']])
   +'<p>В прошедшем: <b>werd/werden</b> + причастие. «Кем» вводится словом <b>door</b>.</p>',
  'ex':[['De brief wordt verstuurd.','Письмо отправляется.'],['De aanvraag werd afgewezen.','Заявка была отклонена.']]},
 {'t':'quiz','k':'Выбери пассив','q':'Как сказать «Договор подписывается»?','opts':['Het contract wordt getekend.','Het contract tekent.','Het contract is teken.','Het contract worden getekend.']},
 {'t':'quiz','k':'Прошедшее','q':'«Заявка была отклонена» —','opts':['De aanvraag werd afgewezen.','De aanvraag wordt afwijzen.','De aanvraag is afwijzen.','De aanvraag afgewezen werd.']},
 {'t':'build','k':'Собери пассив: субъект · worden · … · причастие','tr':'Зарплата выплачивается каждый месяц.','words':['Het','salaris','wordt','elke','maand','betaald'],'ans':['Het','salaris','wordt','elke','maand','betaald']},
 {'t':'build','k':'С «door» (кем)','tr':'Письмо отправляется муниципалитетом.','words':['De','brief','wordt','door','de','gemeente','verstuurd'],'ans':['De','brief','wordt','door','de','gemeente','verstuurd']},
 {'t':'tf','k':'Верно?','q':'В пассиве причастие (getekend, betaald) стоит в конце предложения.','answer':True,'note':'Да: worden спрягается на №2, причастие уходит в конец.'},
 {'t':'gapType','k':'Впиши форму worden','q':'Het formulier ___ ingevuld. (заполняется)','ans':'wordt','hint':'3-е лицо ед.ч.'},
 {'t':'speak','k':'Говорение','phrase':'De beslissing wordt volgende week genomen.','tr':'Решение будет принято на следующей неделе.'},
]},
# 2) Er-конструкции
{'title':'Грамматика: er (er is, er wordt) 📍','theme':'Общество и среда','idx':2,'steps':[
 {'t':'explain','k':'Правило B1 · слово er','b':'📍 «er» — 4 роли',
  'html':'<p>Маленькое <b>er</b> — одно из самых частых слов. Главные роли:</p>'
   +rule([['1. Наличие','<b>Er is</b> een probleem. — Есть проблема.'],
          ['2. Место (там)','Ik woon <b>er</b> al jaren. — Я там живу много лет.'],
          ['3. Пассив без лица','<b>Er wordt</b> veel gepraat. — Много говорят.'],
          ['4. er + предлог','Ik denk <b>er</b>aan. — Я думаю об этом.']])
   +'<p>При числах: <b>Hoeveel kinderen heb je? — Ik heb <u>er</u> twee.</b></p>',
  'ex':[['Er zijn veel regels.','Есть много правил.'],['Er wordt gestemd.','Идёт голосование.']]},
 {'t':'quiz','k':'Наличие','q':'«Есть решение» —','opts':['Er is een oplossing.','Is een oplossing.','Het is een oplossing er.','Daar een oplossing.']},
 {'t':'quiz','k':'При числе','q':'«У меня их двое» (детей) —','opts':['Ik heb er twee.','Ik heb twee er.','Ik heb ze twee.','Er ik heb twee.']},
 {'t':'gapType','k':'Впиши er','q':'___ wordt veel over politiek gepraat. (много говорят)','ans':'Er','hint':'начало предложения'},
 {'t':'build','k':'Собери с er','tr':'Есть большая проблема в обществе.','words':['Er','is','een','groot','probleem','in','de','samenleving'],'ans':['Er','is','een','groot','probleem','in','de','samenleving']},
 {'t':'tf','k':'Верно?','q':'«Er» может заменять «об этом» вместе с предлогом: erover, eraan, ermee.','answer':True,'note':'Да: er + предлог = «об этом / этим». Denk je eraan? — Ты об этом помнишь?'},
 {'t':'speak','k':'Говорение','phrase':'Er zijn veel mogelijkheden in Nederland.','tr':'В Нидерландах много возможностей.'},
]},
# 3) Относительные придаточные die/dat
{'title':'Грамматика: die / dat (который) 🔗','theme':'Общество и среда','idx':4,'steps':[
 {'t':'explain','k':'Правило B1 · betrekkelijke bijzin','b':'🔗 die / dat = «который»',
  'html':'<p>Относительное предложение уточняет существительное. Выбор слова зависит от артикля:</p>'
   +rule([['de-слово → die','de man <b>die</b> hier werkt — мужчина, который здесь работает'],
          ['het-слово → dat','het huis <b>dat</b> ik koop — дом, который я покупаю'],
          ['мн. число → die','de mensen <b>die</b> stemmen — люди, которые голосуют']])
   +'<p>Важно: в придаточном <b>глагол уходит в конец</b>: de vrouw die naast mij <b>woont</b>.</p>',
  'ex':[['de collega die mij helpt','коллега, который мне помогает'],['het contract dat ik teken','контракт, который я подписываю']]},
 {'t':'quiz','k':'de of het?','q':'«Дом, который я снимаю» — het huis ___ ik huur','opts':['dat','die','wat','wie']},
 {'t':'quiz','k':'de-слово','q':'«Человек, который живёт рядом» — de man ___ naast mij woont','opts':['die','dat','wat','welke']},
 {'t':'build','k':'Глагол в конец придаточного!','tr':'Женщина, которая здесь работает, милая.','words':['De','vrouw','die','hier','werkt','is','aardig'],'ans':['De','vrouw','die','hier','werkt','is','aardig']},
 {'t':'gapType','k':'Впиши die/dat','q':'Het boek ___ ik lees is moeilijk.','ans':'dat','hint':'het-слово'},
 {'t':'tf','k':'Верно?','q':'После die/dat спрягаемый глагол уходит в конец придаточного предложения.','answer':True,'note':'Да: de man die hier werkt — глагол werkt в конце.'},
 {'t':'speak','k':'Говорение','phrase':'De cursus die ik volg is heel nuttig.','tr':'Курс, который я прохожу, очень полезен.'},
]},
# 4) hoewel / terwijl
{'title':'Грамматика: hoewel, terwijl 🧩','theme':'Карьера','idx':4,'steps':[
 {'t':'explain','k':'Правило B1 · уступка и контраст','b':'🧩 hoewel (хотя), terwijl (в то время как)',
  'html':'<p>Это союзы придаточного — после них <b>глагол уходит в конец</b>, как после omdat.</p>'
   +rule([['hoewel','хотя','Hoewel ik moe ben, werk ik door.'],
          ['terwijl','пока / тогда как','Terwijl hij belt, schrijf ik.'],
          ['toch (главное)','всё же','Het regent, toch ga ik fietsen.']])
   +'<p>Если придаточное <b>впереди</b>, в главном — инверсия: <b>Hoewel het duur is, koop ik het.</b></p>',
  'ex':[['Hoewel het moeilijk is, geef ik niet op.','Хотя это трудно, я не сдаюсь.'],['Terwijl zij kookt, dek ik de tafel.','Пока она готовит, я накрываю на стол.']]},
 {'t':'quiz','k':'Хотя','q':'«Хотя у меня мало времени, я помогу» —','opts':['Hoewel ik weinig tijd heb, help ik.','Hoewel ik heb weinig tijd, ik help.','Ik help hoewel weinig tijd.','Hoewel help ik weinig tijd heb.']},
 {'t':'quiz','k':'Пока','q':'«Пока он спит, я работаю» —','opts':['Terwijl hij slaapt, werk ik.','Terwijl hij werkt ik slaapt.','Terwijl slaapt hij, ik werk.','Ik werk terwijl slaapt hij.']},
 {'t':'build','k':'Придаточное впереди → инверсия','tr':'Хотя это дорого, я это покупаю.','words':['Hoewel','het','duur','is','koop','ik','het'],'ans':['Hoewel','het','duur','is','koop','ik','het']},
 {'t':'gapType','k':'Впиши союз','q':'___ ik ziek ben, ga ik naar mijn werk. (хотя)','ans':'Hoewel','hint':'уступка'},
 {'t':'tf','k':'Верно?','q':'После «terwijl» глагол остаётся на втором месте.','answer':False,'note':'Нет! terwijl — союз придаточного, глагол уходит в конец.'},
 {'t':'speak','k':'Говорение','phrase':'Hoewel het lastig is, blijf ik het proberen.','tr':'Хотя это сложно, я продолжаю пытаться.'},
]},
# 5) Будущее zullen / gaan
{'title':'Грамматика: будущее — zullen, gaan ⏩','theme':'Здоровье и инстанции','idx':2,'steps':[
 {'t':'explain','k':'Правило B1 · toekomende tijd','b':'⏩ Будущее: gaan, zullen',
  'html':'<p>Три способа сказать о будущем:</p>'
   +rule([['gaan + inf.','намерение/план','Ik <b>ga</b> morgen bellen.'],
          ['zullen + inf.','обещание/предложение','Ik <b>zal</b> het regelen.'],
          ['настоящее + время','по контексту','Ik <b>bel</b> je straks.']])
   +'<p><b>Zullen we…?</b> — вежливое предложение: «Давай…?» → <b>Zullen we beginnen?</b></p>'
   +rule([['ik','zal'],['jij','zult / zal'],['hij/zij','zal'],['wij/jullie/zij','zullen']]),
  'ex':[['Ik zal het formulier invullen.','Я заполню бланк.'],['We gaan volgende week verhuizen.','Мы переезжаем на следующей неделе.']]},
 {'t':'quiz','k':'Обещание','q':'«Я это улажу» (обещаю) —','opts':['Ik zal het regelen.','Ik ga het regel.','Ik zullen regelen het.','Ik regel zal het.']},
 {'t':'quiz','k':'Предложение','q':'«Давай начнём?» —','opts':['Zullen we beginnen?','Gaan we begint?','Wij zal beginnen?','Beginnen zullen we?']},
 {'t':'gapType','k':'Впиши форму zullen','q':'Ik ___ je morgen bellen.','ans':'zal','hint':'ik-форма'},
 {'t':'build','k':'Собери с gaan','tr':'Я запишусь к врачу завтра.','words':['Ik','ga','morgen','een','afspraak','maken'],'ans':['Ik','ga','morgen','een','afspraak','maken']},
 {'t':'tf','k':'Верно?','q':'«Zullen we…?» — это вежливое предложение сделать что-то вместе.','answer':True,'note':'Да: Zullen we koffie drinken? — Давай выпьем кофе?'},
 {'t':'speak','k':'Говорение','phrase':'Ik zal de aanvraag vandaag versturen.','tr':'Я отправлю заявку сегодня.'},
]},
# 6) te + infinitief
{'title':'Грамматика: te + инфинитив 🎯','theme':'Здоровье и инстанции','idx':4,'steps':[
 {'t':'explain','k':'Правило B1 · te + infinitief','b':'🎯 …te doen, om…te, zonder…te',
  'html':'<p>После многих глаголов и выражений инфинитив идёт с <b>te</b> и уходит в конец:</p>'
   +rule([['proberen te','пытаться','Ik probeer het <b>te</b> begrijpen.'],
          ['vergeten te','забыть','Hij vergeet <b>te</b> bellen.'],
          ['om … te','чтобы','Ik bel <b>om</b> een afspraak <b>te</b> maken.'],
          ['zonder … te','не делая','Hij vertrekt <b>zonder</b> iets <b>te</b> zeggen.']])
   +'<p>⚠️ После <b>kunnen, moeten, willen, zullen, gaan</b> — <u>без</u> te: Ik moet gaan.</p>',
  'ex':[['Ik hoop je snel te zien.','Надеюсь скоро тебя увидеть.'],['Het is belangrijk om te sporten.','Важно заниматься спортом.']]},
 {'t':'quiz','k':'Чтобы','q':'«Я звоню, чтобы записаться» —','opts':['Ik bel om een afspraak te maken.','Ik bel om maak een afspraak.','Ik bel te een afspraak maken.','Ik bel voor afspraak maken.']},
 {'t':'quiz','k':'te или без?','q':'Какое верно?','opts':['Ik moet gaan.','Ik moet te gaan.','Ik moet om te gaan.','Ik gaan moet.']},
 {'t':'gapType','k':'Нужно ли te? Впиши te или -','q':'Ik probeer het ___ begrijpen.','ans':'te','hint':'после proberen'},
 {'t':'build','k':'Собери om…te','tr':'Важно вовремя заполнять бланки.','words':['Het','is','belangrijk','om','formulieren','op','tijd','in','te','vullen'],'ans':['Het','is','belangrijk','om','formulieren','op','tijd','in','te','vullen']},
 {'t':'tf','k':'Верно?','q':'После moeten, kunnen, willen инфинитив идёт БЕЗ te.','answer':True,'note':'Да: Ik wil gaan (не «wil te gaan»).'},
 {'t':'speak','k':'Говорение','phrase':'Ik probeer elke dag Nederlands te oefenen.','tr':'Я стараюсь каждый день практиковать нидерландский.'},
]},
]

out={'note':'Грамматика B1: пассив, er, die/dat, hoewel/terwijl, будущее zullen/gaan, te+инфинитив. Символьные ссылки {theme,idx} → узлы 📐 после B1-уроков.','parts':parts}
json.dump(out,open(ROOT+'/data/grammar_b1.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('grammar_b1.json:',len(parts),'частей')
for p in parts:print('  ',p['title'],'| theme=',p['theme'],'idx=',p['idx'],'| шагов',len(p['steps']))
