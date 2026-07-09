#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборщик app.html из данных.

Контент (банк слов, автоуроки 39–79, диалоги, официальный словарь A1) живёт в data/*.json —
редактируй JSON и запускай `python3 build.py`: скрипт пересоберёт соответствующие блоки
внутри app.html. Код приложения (движок, экраны, стили, ручные уроки 1–38) не трогается.

Блоки в app.html размечены якорями-комментариями:
  H_GEN «Банк A1–A2 …»  → var BANK, META.push, Object.assign(DATA), THEMES[..].lessons, srsLoadBank
  H_DLG «Диалоги …»      → DATA[n].parts.push(часть «Диалог») из data/dialogues.json
  H_WL  «Официальный словарь …» → var WL + srsLoadWL (до "function renderNode")

JSON — это валидный JS-литерал, поэтому данные вставляются через json.dumps без преобразований.
"""
import json,os,sys
ROOT=os.path.dirname(os.path.abspath(__file__))
def J(name):return json.load(open(os.path.join(ROOT,'data',name),encoding='utf-8'))
def js(o):return json.dumps(o,ensure_ascii=False,separators=(',',':'))

H_GEN="/* ===== Банк A1–A2 (из data/dutch_a1_a2_5000.json) + сгенерированные уроки ===== */"
H_DLG="/* ===== Диалоги тем 3–8 (часть «Диалог» в первом уроке темы) ===== */"
H_WL="/* ===== Официальный словарь TaalCompleet A1 (data/taalcompleet_a1_woordenlijst.json) ===== */"
END_ANCHOR="function renderNode(nd,off,th){"

def build_gen():
    bank=J('bank.json');gen=J('lessons_generated.json')
    out=[H_GEN]
    out.append("var BANK="+js(bank['themes'])+";")
    out.append("META.push.apply(META,"+js(gen['meta'])+");")
    out.append("Object.assign(DATA,"+js(gen['lessons'])+");")
    for ti,nums in gen['themeLessons'].items():
        out.append("THEMES["+ti+"].lessons=THEMES["+ti+"].lessons.concat("+js(nums)+");")
    out.append("function srsLoadBank(){var i=0;BANK.forEach(function(th){th.w.forEach(function(p){if(!SRS[p[0]]){SRS[p[0]]={tr:p[1],box:1,due:vDay+(i%45),wrong:0};i++;}});});}")
    return "\n".join(out)+"\n"

def build_dlg():
    d=J('dialogues.json')
    return (H_DLG+"\n"
     +js(d['dialogues'])
     +".forEach(function(d){if(DATA[d.lesson])DATA[d.lesson].parts.push({t:d.title,steps:d.steps});});\n")

def build_wl():
    wl=J('taalcompleet_a1_woordenlijst.json')
    LABEL={1:'Знакомство (Hallo!)',2:'Школа (De school)',3:'Жильё (Wonen)',4:'Еда и напитки (Eten en drinken)',
     5:'Здоровье (De dokter)',6:'Одежда (De kleding)',7:'Путешествия (Reizen)',8:'Досуг (Vrije tijd)'}
    themes=[]
    for t in range(1,9):
        seen=set();pairs=[]
        for w in wl['words']:
            if w['theme']!=t:continue
            disp=(w.get('article','')+' '+w['nl']).strip() if (w.get('pos')=='noun' and w.get('article')) else w['nl']
            if disp.lower() in seen:continue
            seen.add(disp.lower());pairs.append([disp,w['ru']])
        themes.append({'t':LABEL[t],'w':pairs})
    return (H_WL+"\n"
     +"var WL="+js(themes)+";\n"
     +"function srsLoadWL(){var i=0;WL.forEach(function(th){th.w.forEach(function(p){if(!SRS[p[0]]){SRS[p[0]]={tr:p[1],box:1,due:vDay+(i%45),wrong:0};i++;}});});}\n")

def main():
    path=os.path.join(ROOT,'app.html')
    app=open(path,encoding='utf-8').read()
    i=app.index(H_GEN);j=app.index(H_WL)
    k=app.index(END_ANCHOR,j)
    app=app[:i]+build_gen()+build_dlg()+app[j:]  # регенерируем GEN+DLG, WL ниже
    # теперь заменим WL-блок (границы сдвинулись — ищем заново)
    j=app.index(H_WL);k=app.index(END_ANCHOR,j)
    app=app[:j]+build_wl()+app[k:]
    open(path,'w',encoding='utf-8').write(app)
    print("app.html rebuilt:",len(app),"bytes")

if __name__=='__main__':
    main()
