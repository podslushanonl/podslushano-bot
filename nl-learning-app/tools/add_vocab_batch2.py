# -*- coding: utf-8 -*-
"""Батч №2: только ГЕНУИННО новые слова (проверка против всех известных лемм).
Ситуативная/абстрактная лексика A2/B1. Идемпотентно."""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
known=set(json.load(open('/tmp/lem.json'))) if os.path.exists('/tmp/lem.json') else set()

# кандидаты по темам (A1 append / A2 new_themes)
A1={
'Знакомство':[
 ['de indruk','впечатление'],['betrouwbaar','надёжный'],['zelfverzekerd','уверенный в себе'],
 ['bescheiden','скромный'],['spontaan','спонтанный'],['humoristisch','с юмором'],['de eigenschap','качество/черта'],
 ['de gelijkenis','сходство'],['het vertrouwen','доверие'],['de ruzie','ссора'],['het compliment','комплимент'],
],
'Каждый день':[
 ['de planning','планирование'],['regelen','улаживать'],['het gedoe','хлопоты'],['de klus','дело/задача'],
 ['uitstellen','откладывать'],['de prioriteit','приоритет'],['efficiënt','эффективный'],['het overzicht','обзор'],
 ['de deadline','срок'],['dringend','срочный'],['ondertussen','тем временем'],
],
'Здоровье':[
 ['de aandoening','заболевание'],['chronisch','хронический'],['de bijwerking','побочный эффект'],
 ['de diagnose','диагноз'],['de verwijzing','направление'],['de ontsteking','воспаление'],['de vermoeidheid','усталость'],
 ['de stress','стресс'],['de burn-out','выгорание'],['het herstel','выздоровление'],['preventief','профилактический'],
],
'Досуг':[
 ['de ontspanning','расслабление'],['de uitdaging','вызов'],['het evenement','мероприятие'],
 ['de deelname','участие'],['het talent','талант'],['creatief','творческий'],['de inspiratie','вдохновение'],
 ['de motivatie','мотивация'],['de prestatie','достижение'],['bewonderen','восхищаться'],
],
'Работа':[
 ['de sfeer','атмосфера'],['de samenwerking','сотрудничество'],['het initiatief','инициатива'],
 ['de verantwoordelijkheid','ответственность'],['de bevoegdheid','полномочие'],['de regeling','договорённость/правило'],
 ['de doelstelling','цель'],['de evaluatie','оценка'],['het conflict','конфликт'],['bemiddelen','посредничать'],
],
}
A2={
'Нидерланды':[
 ['de identiteit','идентичность'],['de diversiteit','разнообразие'],['de nieuwkomer','вновь прибывший'],
 ['de gewoontes','обычаи'],['de omgangsvormen','манеры/этикет'],['de directheid','прямота'],['de afstand','дистанция'],
 ['het klimaat','климат'],['de laaglanden','низины'],['de handel','торговля'],
],
'Дети':[
 ['de ontwikkeling','развитие'],['het gedrag','поведение'],['de grens','граница/предел'],
 ['de zelfstandigheid','самостоятельность'],['stimuleren','стимулировать'],['de verwennerij','баловство'],
 ['de puberteit','пубертат'],['het vertrouwen','доверие'],['begeleiden','сопровождать'],['de aandacht','внимание'],
],
'Образование':[
 ['de vaardigheid','навык'],['de kennis','знание'],['het inzicht','понимание'],['de theorie','теория'],
 ['de praktijk','практика'],['de vooruitgang','прогресс'],['de motivatie','мотивация'],['de concentratie','концентрация'],
 ['zelfstandig','самостоятельно'],['de begeleiding','сопровождение'],
],
'Gemeente':[
 ['de procedure','процедура'],['de beschikking','решение (офиц.)'],['het bezwaar','возражение'],
 ['de termijn','срок'],['de verplichting','обязанность'],['de voorwaarde','условие'],['de regeling','порядок/правило'],
 ['de instantie','инстанция'],['de aanvrager','заявитель'],['bevestigen','подтверждать'],
],
}

def lm(d):return d.split(' ')[-1].lower()
ex=json.load(open(ROOT+'/data/extra_words.json',encoding='utf-8'))
added=0;skipped=0
for th,ws in A1.items():
    lst=ex['append'].setdefault(th,[])
    have={lm(w[0]) for w in lst}|known
    for d,ru in ws:
        if lm(d) in have: skipped+=1; continue
        have.add(lm(d));lst.append([d,ru]);added+=1
byname={t['t']:t for t in ex['new_themes']}
for th,ws in A2.items():
    t=byname.get(th)
    if not t:continue
    have={lm(w[0]) for w in t['w']}|known
    for d,ru in ws:
        if lm(d) in have: skipped+=1; continue
        have.add(lm(d));t['w'].append([d,ru]);added+=1
json.dump(ex,open(ROOT+'/data/extra_words.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(f'Батч №2: добавлено новых {added}, пропущено (уже есть) {skipped}')
