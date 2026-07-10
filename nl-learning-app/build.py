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

H_MAN="/* ===== УРОКИ 1–38 (data/lessons_manual.json) ===== */"
H_TT="/* ===== ТРЕНИРОВКИ + ТЕСТ УРОВНЯ (data/training.json, data/test.json) ===== */"
H_BASE="/* ======= Темы 3–8: уроки 21–38 (TaalCompleet A1) ======= */"
H_GEN="/* ===== Банк A1–A2 (из data/dutch_a1_a2_5000.json) + сгенерированные уроки ===== */"
H_DLG="/* ===== Диалоги тем 3–8 (часть «Диалог» в первом уроке темы) ===== */"
H_WL="/* ===== Официальный словарь TaalCompleet A1 (data/taalcompleet_a1_woordenlijst.json) ===== */"
END_ANCHOR="function renderNode(nd,off,th){"

def build_manual():
    man=J('lessons_manual.json')
    return (H_MAN+"\n"
     +"const META="+js(man['meta'])+";\n"
     +"const DATA="+js(man['lessons'])+";\n")

def build_traintest():
    tr=J('training.json');te=J('test.json')
    return (H_TT+"\n"
     +"const TRAIN="+js(tr['train'])+";\n"
     +"const TEST="+js(te['test'])+";\n")

def build_base():
    man=J('lessons_manual.json')
    out=[H_BASE]
    for ti,nums in man['themeBase'].items():
        out.append("THEMES["+ti+"].lessons="+js(nums)+";")
    return "\n".join(out)+"\n"

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
    parts=d['dialogues']
    try: parts=parts+J('stories.json')['stories']
    except FileNotFoundError: pass
    try: parts=parts+J('grammar_a2.json')['parts']
    except FileNotFoundError: pass
    try: parts=parts+J('handige_zinnen.json')['parts']
    except FileNotFoundError: pass
    try: parts=parts+J('documents_a2.json')['parts']
    except FileNotFoundError: pass
    try: parts=parts+J('phonetics_puzzles.json')['parts']
    except FileNotFoundError: pass
    try: cw=J('crosswords.json')['crosswords']
    except FileNotFoundError: cw={}
    # символьные ссылки {theme, idx} → номер урока (не ломаются при росте банка)
    gen=J('lessons_generated.json');bankj=J('bank.json')
    tmap={th['t']:gen['themeLessons'].get(str(ti),[]) for ti,th in enumerate(bankj['themes'])}
    resolved=[]
    for d in parts:
        if 'theme' in d:
            ls=tmap.get(d['theme'],[])
            if d['idx']>=len(ls):
                print('  ! пропущена часть «%s»: в теме «%s» нет урока #%d'%(d['title'],d['theme'],d['idx']))
                continue
            d=dict(d);d['lesson']=ls[d['idx']]
        resolved.append(d)
    return (H_DLG+"\n"
     +js(resolved)
     +".forEach(function(d){if(DATA[d.lesson])DATA[d.lesson].parts.push({t:d.title,steps:d.steps});});\n"
     +"var CROSSWORDS="+js(cw)+";\n")

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
    # WLX — дополнительные разделы из вычитки: мн. число, формы глаголов, фразы (mijn/deze)
    vet=J('vetted_translations.json')['items']
    plu=[];vf=[];ph=[];seen_ph=set()
    for v in vet:
        if v['quality']=='correct' and v['type']=='noun_plural':plu.append([v['nl'],v['ru_vetted']])
        elif v['quality']=='form' and v['type']=='verb_form':vf.append([v['nl'],v['ru_vetted']])
        elif v['quality']=='correct' and v['type'] in ('possessive_phrase','demonstrative_phrase'):
            if v['nl'].split(' ')[0] in ('mijn','deze','dit') and v['lemma'] not in seen_ph:
                seen_ph.add(v['lemma']);ph.append([v['nl'],v['ru_vetted']])
    # служебные слова из базы 5000 (местоимения, наречия, предлоги, союзы, числа, дни, месяцы…)
    base=J('dutch_a1_a2_5000.json')['items']
    FUNC_T={'pronoun':1,'adverb':1,'question':1,'answer':1,'connector':1,'preposition':1,'word':1,'phrase':1,'number':1,'ordinal':1,'day':1,'month':1}
    fw=[];seen_fw=set()
    for it in base:
        if it['type'] in FUNC_T:
            ru=(it.get('ru') or '').strip()
            if not ru or ':' in ru or '(' in ru:continue
            nl=it['nl']
            if nl.lower() in seen_fw:continue
            seen_fw.add(nl.lower());fw.append([nl,ru])
    # неправильные глаголы A2 (imperfect + perfectum) — из фото учебника, стр. 365–367
    try:
        iv=J('irregular_verbs.json')['verbs']
        ivw=[[v[0]+' — '+v[1]+' — '+v[2],v[3]] for v in iv]
    except FileNotFoundError:
        ivw=[]
    # Handige zinnen (стр. 368–369 учебника) — готовые фразы по ситуациям
    try:
        hz=J('handige_zinnen.json')['sections']
    except FileNotFoundError:
        hz=[]
    wlx=[{'t':'Множественное число (meervoud)','w':plu},
         {'t':'Формы глаголов (ik · jij · hij…)','w':vf},
         {'t':'⚡ Неправильные глаголы A2 (imperfect · perfectum)','w':ivw}]\
        +hz\
        +[{'t':'Фразы: мой / этот (mijn · deze)','w':ph},
         {'t':'Служебные слова (частые)','w':fw}]
    # слова банка уроков, которых ещё нет в словаре — чтобы счётчик отражал реальный объём
    bankj=J('bank.json')['themes']
    have={p[0].lower() for th in themes for p in th['w']}
    for sec in wlx:have|={p[0].lower() for p in sec['w']}
    bw=[];seen_b=set()
    for th in bankj:
        for d,ru in th['w']:
            k=d.lower()
            if k in have or k in seen_b:continue
            seen_b.add(k);bw.append([d,ru])
    wlx.append({'t':'Слова уроков (банк всех тем)','w':bw})
    return (H_WL+"\n"
     +"var WL="+js(themes)+";\n"
     +"var WLX="+js(wlx)+";\n"
     +"function srsLoadWL(){var i=0;WL.forEach(function(th){th.w.forEach(function(p){if(!SRS[p[0]]){SRS[p[0]]={tr:p[1],box:1,due:vDay+(i%45),wrong:0};i++;}});});}\n"
     +"function srsLoadWLX(){var i=0;WLX.forEach(function(th){th.w.forEach(function(p){if(!SRS[p[0]]){SRS[p[0]]={tr:p[1],box:1,due:vDay+(i%60),wrong:0};i++;}});});}\n")

def region_replace(app,start_anchor,end_anchor,content):
    i=app.index(start_anchor);k=app.index(end_anchor,i)
    return app[:i]+content+app[k:]

def main():
    path=os.path.join(ROOT,'app.html')
    app=open(path,encoding='utf-8').read()
    # 1) ручные уроки 1–38 (первый прогон: якорь — сама декларация const META=)
    man_start=H_MAN if H_MAN in app else "const META="
    app=region_replace(app,man_start,"const PARTS=",build_manual())
    # 1½) тренировки + тест уровня
    tt_start=H_TT if H_TT in app else "const TRAIN="
    app=region_replace(app,tt_start,"let tIdx=0",build_traintest()+"")
    # 2) базовые списки уроков тем 3–8
    app=region_replace(app,H_BASE,H_GEN,build_base())
    # 3) банк + автоуроки; 4) диалоги + истории
    app=region_replace(app,H_GEN,H_DLG,build_gen())
    app=region_replace(app,H_DLG,H_WL,build_dlg())
    # 5) официальный словарь A1
    app=region_replace(app,H_WL,END_ANCHOR,build_wl())
    open(path,'w',encoding='utf-8').write(app)
    print("app.html rebuilt:",len(app),"bytes")

if __name__=='__main__':
    main()
