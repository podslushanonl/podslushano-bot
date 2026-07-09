# -*- coding: utf-8 -*-
"""Углубление ручных уроков 1–20:
1) части «Предложения и слух» пересобираются из батчей №1+№2 + 2 Q&A-шага;
2) аудирование слов — неугадываемые похожие варианты (из официального словаря);
3) правила-таблицы в уроки 2 (zijn+местоимения), 3 (hebben), 5 (числа), 9 (niet/geen)."""
import json,re
ROOT='/home/user/podslushano-bot/nl-learning-app'
d=json.load(open(ROOT+'/data/lessons_manual.json',encoding='utf-8'))
b1=json.load(open(ROOT+'/data/sentences_batch1.json',encoding='utf-8'))['items']
b2=json.load(open(ROOT+'/data/sentences_batch2.json',encoding='utf-8'))['items']
qa=json.load(open(ROOT+'/data/qa_pairs.json',encoding='utf-8'))['pairs']
wl=json.load(open(ROOT+'/data/taalcompleet_a1_woordenlijst.json',encoding='utf-8'))['words']
batch=b1+b2
ALL=[b['nl'] for b in batch]
WLNL=[( (w.get('article','')+' '+w['nl']).strip() if w.get('article') else w['nl'] ) for w in wl]

def similar(word,exclude):
    """похожие слова: та же первая буква → близкая длина"""
    b=word.split(' ')[-1].lower()
    c1=[x for x in WLNL if x.split(' ')[-1][:1].lower()==b[:1] and x.lower()!=word.lower() and x not in exclude]
    c2=[x for x in WLNL if abs(len(x.split(' ')[-1])-len(b))<=2 and x.lower()!=word.lower() and x not in exclude and x not in c1]
    out=[]
    for grp in (c1,c2):
        for x in grp:
            if x not in out:out.append(x)
            if len(out)>=3:return out
    return out[:3]

# ---------- 1+2) пересборка частей «Предложения и слух» + слух слов ----------
for n in range(2,21):
    L=d['lessons'][str(n)]
    pool=[b for b in batch if b['theme']==(0 if n<=10 else 1)]
    # заменяем часть
    for pi,pt in enumerate(L['parts']):
        if pt['t']=='Предложения и слух':
            off=(n*11)%max(1,len(pool)-12)
            pick=pool[off:off+10]
            steps=[{'t':'explain','k':'Слово в предложении','b':'📖 Практика','html':'<p>Закрепим материал урока в живых предложениях и вопросах — как в реальном разговоре.</p>'}]
            for b in pick[:2]:
                toks=re.sub(r'[.?!]$','',b['nl']).split(' ')
                steps.append({'t':'build','k':'Предложение','tr':b['ru'],'words':toks,'ans':toks})
            for j,b in enumerate(pick[2:4]):
                distr=[x for x in ALL if x!=b['nl']][(n*13+j*5)%(len(ALL)-4):][:3]
                steps.append({'t':'listen','k':'Аудирование','audio':b['nl'],'q':'Какое предложение прозвучало?','opts':[b['nl']]+distr})
            b=pick[4]
            if b['lemma'] in b['nl']:
                steps.append({'t':'gapType','k':'На слух','audio':b['nl'],'q':b['nl'].replace(b['lemma'],'___',1),'answer':[b['lemma']],'ph':'…'})
            b=pick[5]
            rus=[x['ru'] for x in pool if x['ru']!=b['ru']][(n*3)%(len(pool)-4):][:3]
            steps.append({'t':'quiz','k':'Понимание','q':'Что значит: «'+b['nl']+'»?','opts':[b['ru']]+rus})
            # Q&A: вопрос на слух → выбор ответа → произнеси
            qs=[q for q in qa if q['theme']==(0 if n<=10 else 1)] or qa
            q=qs[n%len(qs)]
            steps.append({'t':'listen','k':'Вопрос на слух','audio':q['q_nl'],'q':'Тебя спросили — что именно?','opts':[q['q_nl']]+[x['q_nl'] for x in qa if x['q_nl']!=q['q_nl']][(n*7)%(len(qa)-4):][:3]})
            steps.append({'t':'quiz','k':'Твой ответ','q':'«'+q['q_nl']+'» ('+q['q_ru']+') — что ответишь?','opts':[q['a_nl']]+[x['a_nl'] for x in qa if x['a_nl']!=q['a_nl']][(n*5)%(len(qa)-4):][:3]})
            steps.append({'t':'speak','k':'Говорение','phrase':q['a_nl'],'tr':q['a_ru']})
            L['parts'][pi]={'t':'Предложения и разговор','steps':steps}
# слух слов: неугадываемые варианты (для аудио из 1-2 слов)
fixed=0
for n in range(1,21):
    for pt in d['lessons'][str(n)]['parts']:
        for st in pt['steps']:
            if st.get('t')=='listen' and st.get('opts') and len(st.get('audio','').split(' '))<=2:
                corr=st['opts'][0]
                st['opts']=[corr]+similar(corr,set(st['opts']))
                fixed+=1
print("listen-шагов обновлено:",fixed)

# ---------- 3) правила-таблицы ----------
def table(rows):
    return '<div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:14px">'+''.join(
     '<div style="background:var(--surface);border:1px solid var(--brd);border-radius:10px;padding:7px 10px"><b>'+a+'</b></div>'
     +'<div style="background:var(--surface);border:1px solid var(--brd);border-radius:10px;padding:7px 10px;color:var(--ink-2)">'+b+'</div>' for a,b in rows)+'</div>'
RULES={
 '2':{'t':'📐 Правило: глагол ZIJN (быть)','b':'📐 Правило',
  'html':'<p><b>Zijn (быть)</b> — самый важный глагол. В русском мы говорим «я — Анна», в нидерландском связка обязательна: <b>Ik ben Anna</b>. Выучи таблицу:</p>'+table([('ik ben','я (есть)'),('jij bent','ты'),('u bent','Вы (вежл.)'),('hij / zij is','он / она'),('wij zijn','мы'),('jullie zijn','вы'),('zij zijn','они')])+'<div class="rule" style="margin-top:8px">❗ В вопросе -t исчезает: <b>Ben jij…?</b> (а не Bent jij)</div>',
  'ex':[['Ik ben Anna.','Я — Анна.'],['Ben jij Tom?','Ты — Том?']]},
 '3':{'t':'📐 Правило: глагол HEBBEN (иметь)','b':'📐 Правило',
  'html':'<p>Русское «у меня есть…» по-нидерландски — «я имею»: <b>Ik heb een vraag</b> = У меня есть вопрос. Таблица <b>hebben</b>:</p>'+table([('ik heb','у меня есть'),('jij hebt','у тебя'),('u hebt / heeft','у Вас'),('hij / zij heeft','у него / неё'),('wij hebben','у нас'),('jullie hebben','у вас'),('zij hebben','у них')])+'<div class="rule" style="margin-top:8px">❗ hij <b>heeft</b> — особая форма (не «hebt»)</div>',
  'ex':[['Ik heb een vraag.','У меня есть вопрос.'],['Zij heeft twee kinderen.','У неё двое детей.']]},
 '5':{'t':'📐 Правило: числа','b':'📐 Правило',
  'html':'<p>Числа 0–12 учим наизусть, дальше — правила:</p>'+table([('13–19','+ tien: der<b>tien</b>, veer<b>tien</b>…'),('20, 30, 40…','twintig, dertig, veertig…'),('21, 22…','❗ наоборот: een-en-twintig (один-и-двадцать)'),('35','vijf-en-dertig (пять-и-тридцать)')])+'<div class="rule" style="margin-top:8px">По-русски «двадцать один», по-нидерландски «один-и-двадцать» — <b>единицы вперёд!</b></div>',
  'ex':[['eenentwintig','21 (один-и-двадцать)'],['vijfendertig','35 (пять-и-тридцать)']]},
 '9':{'t':'📐 Правило: NIET или GEEN?','b':'📐 Правило',
  'html':'<p>В нидерландском два «не» — и выбирать нужно правильно:</p>'+table([('GEEN','= «нет ни одного». Перед существительным без артикля: Ik heb <b>geen</b> auto.'),('NIET','всё остальное: после глагола, перед прилагательным: Ik werk <b>niet</b>. Het is <b>niet</b> duur.')])+'<div class="rule" style="margin-top:8px">Проверка: можно сказать «ни одного»? → geen. Нельзя? → niet.</div>',
  'ex':[['Ik heb geen tijd.','У меня нет времени.'],['Ik slaap niet.','Я не сплю.']]},
}
for n,rule in RULES.items():
    steps=d['lessons'][n]['parts'][0]['steps']
    if not any(s.get('b')=='📐 Правило' for s in steps):
        steps.insert(1,{'t':'explain','k':rule['t'],'b':rule['b'],'html':rule['html'],'ex':rule.get('ex',[])})
print("правила вставлены: уроки",list(RULES))
json.dump(d,open(ROOT+'/data/lessons_manual.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("saved")
