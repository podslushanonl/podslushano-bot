# -*- coding: utf-8 -*-
"""Генерирует data/bank.json, data/lessons_generated.json, data/dialogues.json (чистый JSON)."""
import json
import os
import re
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
# батч №1: новые предложения приоритетнее шаблонных
for _bf in ("sentences_batch1.json","sentences_batch2.json","sentences_batch3.json","sentences_batch4.json"):
    try:
        for it in json.load(open(ROOT+"/data/"+_bf,encoding='utf-8'))['items']:
            VETL.setdefault(it['lemma'],[]).insert(0,{'nl':it['nl'],'ru':it['ru']})
    except FileNotFoundError:
        pass
try:
    QA=json.load(open(ROOT+"/data/qa_pairs.json",encoding='utf-8'))['pairs']
except FileNotFoundError:
    QA=[]
def vet_pick(lemma,salt):
    lst=VETL.get(lemma)
    return lst[salt%len(lst)] if lst else None

EMOJI_NL={
 # люди/семья
 'man':'👨','vrouw':'👩','kind':'🧒','baby':'👶','jongen':'👦','meisje':'👧','moeder':'👩‍🦳','vader':'👨‍🦳',
 'broer':'👱‍♂️','zus':'👱‍♀️','oma':'👵','opa':'👴','familie':'👪','vriend':'🧑‍🤝‍🧑','vriendin':'👭','dokter':'👨‍⚕️',
 'docent':'👨‍🏫','leraar':'👨‍🏫','lerares':'👩‍🏫','collega':'🧑‍💼','buurman':'🙋‍♂️','buurvrouw':'🙋‍♀️',
 # еда/напитки
 'appel':'🍎','banaan':'🍌','brood':'🍞','kaas':'🧀','melk':'🥛','water':'💧','koffie':'☕','thee':'🍵',
 'wijn':'🍷','bier':'🍺','vis':'🐟','vlees':'🥩','kip':'🍗','ei':'🥚','soep':'🍲','rijst':'🍚','pasta':'🍝',
 'tomaat':'🍅','ui':'🧅','wortel':'🥕','aardappel':'🥔','druif':'🍇','peer':'🍐','citroen':'🍋','sinaasappel':'🍊',
 'taart':'🍰','koekje':'🍪','ijs':'🍨','boter':'🧈','suiker':'🍬','zout':'🧂','fruit':'🍇','groente':'🥦',
 'boterham':'🥪','worst':'🌭','sla':'🥬','komkommer':'🥒','bloemkool':'🥦','sap':'🧃','ontbijt':'🍳','lunch':'🥪','avondeten':'🍽️',
 # дом/мебель
 'huis':'🏠','deur':'🚪','raam':'🪟','tuin':'🌳','keuken':'🍳','slaapkamer':'🛏️','badkamer':'🛁','woonkamer':'🛋️',
 'bed':'🛏️','tafel':'🪑','stoel':'🪑','bank':'🛋️','kast':'🗄️','lamp':'💡','televisie':'📺','wc':'🚽','douche':'🚿',
 'trap':'🪜','balkon':'🏢','garage':'🚗','dak':'🏠','muur':'🧱','sleutel':'🔑','flat':'🏢','zolder':'🏚️','lift':'🛗',
 'bad':'🛁','spiegel':'🪞','koelkast':'🧊','oven':'🔥','wasmachine':'🧺','magnetron':'📻','plant':'🪴',
 # школа/работа
 'school':'🏫','boek':'📖','pen':'🖊️','potlood':'✏️','papier':'📄','computer':'💻','bord':'🖼️','klas':'🏫',
 'les':'📚','gum':'🧽','tekst':'📃','woordenboek':'📕','werk':'💼','kantoor':'🏢','baan':'💼','geld':'💶',
 'euro':'💶','rekening':'🧾','kassa':'🧾','bon':'🧾','pinpas':'💳','salaris':'💰','vergadering':'👥','baas':'🧑‍💼',
 'telefoon':'📱','e-mail':'📧','brief':'✉️','agenda':'📅','contract':'📜','formulier':'📋',
 # тело/здоровье
 'hoofd':'🧠','hand':'✋','voet':'🦶','oog':'👁️','oor':'👂','neus':'👃','mond':'👄','arm':'💪','been':'🦵',
 'rug':'🧍','tand':'🦷','haar':'💇','buik':'🤰','knie':'🦵','keel':'🗣️','tandarts':'🦷','apotheek':'💊',
 'medicijn':'💊','ziekenhuis':'🏥','pil':'💊','recept':'📋','koorts':'🌡️','griep':'🤧','pijn':'😣',
 # одежда
 'jas':'🧥','broek':'👖','schoen':'👟','sok':'🧦','trui':'🧶','jurk':'👗','rok':'👗','bril':'👓','hemd':'👕',
 'T-shirt':'👕','pet':'🧢','muts':'🧢','sjaal':'🧣','handschoen':'🧤','laars':'👢','tas':'👜','riem':'🩹','vest':'🧥',
 # транспорт/город
 'auto':'🚗','bus':'🚌','trein':'🚆','fiets':'🚲','tram':'🚋','vliegtuig':'✈️','station':'🚉','halte':'🚏',
 'weg':'🛣️','straat':'🛣️','stad':'🏙️','dorp':'🏘️','kaart':'🗺️','kaartje':'🎫','brug':'🌉','plein':'⛲',
 'winkel':'🏪','supermarkt':'🏪','markt':'🛒','museum':'🏛️','park':'🌳','kerk':'⛪','file':'🚦','stoplicht':'🚦',
 # природа/досуг
 'hond':'🐶','kat':'🐱','paard':'🐴','koe':'🐮','vogel':'🐦','dier':'🐾','boom':'🌳','bloem':'🌸','zon':'☀️',
 'maan':'🌙','regen':'🌧️','sneeuw':'❄️','wind':'💨','zee':'🌊','strand':'🏖️','bos':'🌲','muziek':'🎵',
 'film':'🎬','sport':'⚽','voetbal':'⚽','zwembad':'🏊','vakantie':'🏖️','feest':'🎉','cadeau':'🎁','foto':'📷',
 'krant':'📰','spel':'🎲','bal':'⚽','hobby':'🎨','weer':'🌤️','natuur':'🌿','fietspad':'🚴','hemel':'🌌',
 # время/разное
 'klok':'⏰','uur':'🕐','dag':'☀️','nacht':'🌙','ochtend':'🌅','avond':'🌆','week':'📅','maand':'📅','jaar':'📆',
 'naam':'🪪','vraag':'❓','antwoord':'💬','deurbel':'🔔','prijs':'🏷️','nummer':'🔢','adres':'📍','paspoort':'🪪'
}
def emoji_for(disp,ty):
    lm=disp.split(' ')[-1]
    return EMOJI_NL.get(lm) or EMOJI.get(ty,'📌')
CLEAN={'noun','verb_infinitive','adjective_or_adverb','color'}
EMOJI={'noun':'📦','verb_infinitive':'▶️','adjective_or_adverb':'🔤','color':'🎨'}
MAP=[('Знакомство',['people','family','greetings','pronouns','politeness']),
 ('Каждый день',['time','numbers','frequency','basic','smalltalk','feelings']),
 ('Школа',['school','classroom']),
 ('Еда и напитки',['food','drinks']),
 ('Здоровье',['health']),
 ('Одежда',['clothing','colors']),
 ('Путешествия',['travel','geography']),
 ('Досуг',['leisure','nature','weather','digital']),
 ('Жильё',['home','furniture']),
 ('Работа',['work','money','admin'])]
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


# ---- рукописные дополнения + A2-слова из базы ----
try:
    _ex=json.load(open(ROOT+'/data/extra_words.json',encoding='utf-8'))
except FileNotFoundError:
    _ex={'append':{},'new_themes':[]}
def _lemma(d):return d.split(' ')[-1].lower()
for name,words in _ex.get('append',{}).items():
    for th_name,ws in [(n_,w_) for n_,w_ in zip([b[0] for b in BANK],[b[1] for b in BANK])]:
        pass
for bi,(bname,bws) in enumerate(BANK):
    if bname in _ex.get('append',{}):
        have={_lemma(d) for d,ru,ty in bws}
        for d,ru in _ex['append'][bname]:
            if _lemma(d) not in have:
                ty='noun' if d.startswith(('de ','het ')) else ('verb_infinitive' if d.endswith('en') else 'adjective_or_adverb')
                bws.append((d,ru,ty));have.add(_lemma(d))
# A2-слова из базы 5000 по группам
A2MAP={'Переезд':{'home','furniture'},
 'Нидерланды':{'weather','nature','geography','place','travel','time','adjectives','basic','smalltalk'},
 'Дети':{'family','people','feelings','health'},
 'Магазины':{'shopping','clothing','food','drinks','digital'},
 'Образование':{'school','classroom'},
 'Поиск работы':{'money'},
 'На работе':{'work'},
 'Gemeente':{'admin'}}
a2base={}
for it in items:
    if it.get('level')=='A2' and it['type'] in CLEAN:
        ru=it['ru'].strip()
        if not ru or ':' in ru or '(' in ru:continue
        d=disp_of(it)
        for tn,ds in A2MAP.items():
            if it['theme'] in ds:
                a2base.setdefault(tn,[]).append((d,ru,it['type']));break
for t in _ex.get('new_themes',[]):
    ws=[];have=set()
    for d,ru in t['w']:
        ty='noun' if d.startswith(('de ','het ')) else ('verb_infinitive' if d.endswith('en') else 'adjective_or_adverb')
        if _lemma(d) not in have:ws.append((d,ru,ty));have.add(_lemma(d))
    for d,ru,ty in a2base.get(t['t'],[]):
        if _lemma(d) not in have:ws.append((d,ru,ty));have.add(_lemma(d))
    BANK.append((t['t'],ws))

def pick_distractors(pool,correct,key_idx,n=3,salt=0):
    out=[];i=salt;L=len(pool);g=0
    while len(out)<n and g<L*3:
        v=pool[i%L][key_idx]
        if v!=correct and v not in out:out.append(v)
        i+=1;g+=1
    while len(out)<n:out.append(correct)
    return out

lesson_num=39;meta=[];lessons={};themeLessons={}

def bare(d):
    return d.split(' ')[-1]

def similar_distr(pool,correct,n=3):
    """Похожие варианты для аудирования: та же первая буква, потом похожая длина."""
    cw=bare(correct)
    cands=[x[0] for x in pool if x[0]!=correct]
    same_letter=[c for c in cands if bare(c)[:1]==cw[:1]]
    near_len=[c for c in cands if c not in same_letter and abs(len(bare(c))-len(cw))<=2]
    out=[]
    for grp in (same_letter,near_len,cands):
        for c in grp:
            if c not in out:out.append(c)
            if len(out)>=n:return out
    return out[:n]

def words_html(name,ws):
    rows=''.join('<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--brd)"><b>'+d+'</b><span style="color:var(--ink-2)">'+ru+'</span></div>' for d,ru,ty in ws)
    return '<p>Новые слова темы «'+name+'». Сначала познакомься со ВСЕМИ словами — прослушай каждое (▶ ниже), потом закрепим заданиями.</p><div style="margin-top:8px">'+rows+'</div>'

for ti in range(2,len(BANK)):
    name,ws=BANK[ti]
    chunks=[ws[i:i+8] for i in range(0,len(ws),8)]
    chunks=[c for c in chunks if len(c)>=6][:7]
    nums=[]
    for ci,chunk in enumerate(chunks):
        n=lesson_num;lesson_num+=1;nums.append(n)
        meta.append({'n':n,'t':'Слова: '+name.lower()+' '+str(ci+1),'blk':ti+1})
        half=(len(chunk)+1)//2
        p1w=chunk[:half];p2w=chunk[half:];pool=ws
        parts=[]
        # ---------- ЧАСТЬ 1: Новые слова 1 (знакомство → распознавание) ----------
        st=[{'t':'explain','k':'Урок '+str(ci+1)+' · шаг 1 из '+'5','b':'📖 Новые слова (1/2)','html':words_html(name,p1w),'ex':[[d,ru] for d,ru,ty in p1w]}]
        for d,ru,ty in p1w: st.append({'t':'word','k':'Слово','emoji':emoji_for(d,ty),'nl':d,'tr':ru})
        for j,(d,ru,ty) in enumerate(p1w[:2]):
            st.append({'t':'quiz','k':'Выбор','q':'Как будет «'+ru+'»?','opts':[d]+pick_distractors(pool,d,0,3,salt=j+ci)})
        st.append({'t':'match','k':'Пары','pairs':[[d,ru] for d,ru,ty in p1w]})
        # лишнее слово (как в книге: welk woord past niet in het rijtje?)
        oti=(ti*3+ci+2)%10
        if oti==ti:oti=(oti+1)%10
        ow=BANK[oti][1][(n*7)%len(BANK[oti][1])]
        own3=[d for d,ru,ty in p1w[:3]]
        if len(own3)>=3:
            st.append({'t':'quiz','k':'Лишнее слово','q':'Какое слово НЕ подходит к теме «'+name+'»?','opts':[ow[0]]+own3})
        parts.append({'t':'Новые слова 1','steps':st})
        # ---------- ЧАСТЬ 2: Новые слова 2 (+ слух с ПОХОЖИМИ вариантами) ----------
        st=[{'t':'explain','k':'Шаг 2 из 5','b':'📖 Новые слова (2/2)','html':words_html(name,p2w),'ex':[[d,ru] for d,ru,ty in p2w]}]
        for d,ru,ty in p2w: st.append({'t':'word','k':'Слово','emoji':emoji_for(d,ty),'nl':d,'tr':ru})
        for j,(d,ru,ty) in enumerate(p2w[:2]):
            st.append({'t':'quiz','k':'Значение','q':'«'+d+'» — это…','opts':[ru]+pick_distractors(pool,ru,1,3,salt=j+ci+2)})
        d0,ru0,ty0=p2w[0]
        st.append({'t':'listen','k':'Аудирование','audio':d0,'q':'Что прозвучало? Слушай внимательно — варианты похожи.','opts':[d0]+similar_distr(pool,d0)})
        if len(p2w)>1:
            d1,ru1,ty1=p2w[1]
            st.append({'t':'listen','k':'Аудирование','audio':d1,'q':'А теперь? Варианты снова похожи.','opts':[d1]+similar_distr(pool,d1)})
        wrong=pick_distractors(pool,p2w[0][1],1,1,salt=ci+9)[0]
        st.append({'t':'tf','k':'Верно?','q':'«'+p2w[0][0]+'» значит «'+wrong+'».','answer':False,'note':'Нет: '+p2w[0][0]+' — '+p2w[0][1]+'.'})
        parts.append({'t':'Новые слова 2','steps':st})
        # ---------- ЧАСТЬ 3: Формы и фразы (мой/этот/мн.число) ----------
        st=[{'t':'explain','k':'Шаг 3 из 5','b':'📖 Формы слова','html':'<p>Слово живёт в формах: <b>mijn/jouw</b> (мой/твой), <b>deze/die</b> (этот/тот) и множественное число. Потренируем на словах урока.</p><div class="rule">mijn huis — мой дом · deze man — этот мужчина · de man → de mannen</div>'}]
        used_pl=0
        for d,ru,ty in chunk:
            lm=bare(d);pv=POSSV.get(lm)
            if pv and len(pv)+len(DEMV.get(lm,[]))>=3:
                v=pv[ci%len(pv)]
                distr=[x['nl'] for x in pv if x['nl']!=v['nl']][:3]
                if len(distr)<3 and DEMV.get(lm):
                    distr+=[x['nl'] for x in DEMV[lm] if x['nl'] not in distr][:3-len(distr)]
                st.append({'t':'quiz','k':'Мой, твой…','q':'Как сказать «'+v['ru']+'»?','opts':[v['nl']]+distr[:3]})
                break
        for d,ru,ty in chunk:
            lm=bare(d)
            pairs=[[x['nl'],x['ru']] for x in DEMV.get(lm,[])[:2]]+[[x['nl'],x['ru']] for x in POSSV.get(lm,[])[:2]]
            if len(pairs)>=3:
                st.append({'t':'match','k':'Этот, мой…','pairs':pairs[:4]})
                break
        for d,ru,ty in chunk:
            lm=bare(d);pl=PLUV.get(lm)
            if pl and used_pl<2:
                distr=[];pool_lms=[bare(x[0]) for x in pool];ii=ci*5+1+used_pl*3
                for _ in range(len(pool_lms)*2):
                    cand=PLUV.get(pool_lms[ii%len(pool_lms)]);ii+=1
                    if cand and cand['nl']!=pl['nl'] and cand['nl'] not in distr:distr.append(cand['nl'])
                    if len(distr)>=3:break
                if len(distr)>=2:
                    st.append({'t':'quiz','k':'Мн. число','q':'Множественное число от «'+d+'» ('+ru+') — ?','opts':[pl['nl']]+distr[:3]})
                    used_pl+=1
        for d,ru,ty in p1w[:2]:
            st.append({'t':'translate','k':'Перевод','q':'«'+ru+'»','answer':[d],'ph':'…'})
        if len(st)>=5: parts.append({'t':'Формы и фразы','steps':st})
        else: parts[-1]['steps'].extend(st[1:])
        # ---------- ЧАСТЬ 4: Предложения и слух ----------
        st=[{'t':'explain','k':'Шаг 4 из 5','b':'📖 Слово в предложении','html':'<p>Теперь — целые предложения с новыми словами. Сначала собери, потом услышь и допиши.</p><div class="rule">Dit is … — это … · Waar is …? — где …? · Ik heb … — у меня есть …</div>'}]
        addedS=0;usedNl=set()
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+addedS*2+1)
            if v and addedS<2 and v['nl'] not in usedNl:
                import re as _re
                toks=_re.sub(r'[.?!]$','',v['nl']).split(' ')
                st.append({'t':'build','k':'Предложение','tr':v['ru'],'words':toks,'ans':toks})
                usedNl.add(v['nl']);addedS+=1
        ALL_NL=[x['nl'] for lst in VETL.values() for x in lst]
        sl=0
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+7)
            if v and sl<1 and len(ALL_NL)>=4 and v['nl'] not in usedNl:
                others=[x for x in ALL_NL if x!=v['nl']]
                sd=[];ii=ci*7+3
                for _ in range(len(others)):
                    cand=others[ii%len(others)];ii+=1
                    if cand not in sd:sd.append(cand)
                    if len(sd)>=3:break
                st.append({'t':'listen','k':'Аудирование','audio':v['nl'],'q':'Какое предложение прозвучало?','opts':[v['nl']]+sd})
                usedNl.add(v['nl']);sl+=1
        for d,ru,ty in chunk:
            lm=bare(d);v=vet_pick(lm,ci+11)
            if v and lm in v['nl'] and v['nl'] not in usedNl:
                st.append({'t':'gapType','k':'На слух','audio':v['nl'],'q':v['nl'].replace(lm,'___',1),'answer':[lm],'ph':'…'})
                usedNl.add(v['nl']);break
        # Vul in из списка — одно слово лишнее (как в книге)
        cb=[];cb_l=set()
        for d,ru,ty in list(chunk)+[w for w in ws if w not in chunk]:
            if len(cb)>=3:break
            lm=bare(d)
            if lm in cb_l:continue
            v=vet_pick(lm,ci*5+3)
            if not v or v['nl'] in usedNl:continue
            q=re.sub(r'\b'+re.escape(lm)+r'\b','___',v['nl'],count=1)
            if q==v['nl']:continue
            cb.append([q,lm,v['ru']]);cb_l.add(lm);usedNl.add(v['nl'])
        if len(cb)==3:
            extra=None
            for k2 in range(len(pool)):
                lmx=bare(pool[(n+k2)%len(pool)][0])
                if lmx not in cb_l:extra=lmx;break
            if extra:
                st.append({'t':'clozeBank','k':'Vul in','sents':cb,'bank':[c[1] for c in cb]+[extra]})
        if len(st)>=4: parts.append({'t':'Предложения и слух','steps':st})
        else: parts[-1]['steps'].extend(st[1:])
        # ---------- ЧАСТЬ 5: Говорим и закрепляем ----------
        st=[{'t':'explain','k':'Шаг 5 из 5','b':'📖 Финал урока','html':'<p>Последний рывок: скажи фразы вслух и повтори все слова урока. После урока они попадут в «Умное повторение».</p>'}]
        for d,ru,ty in p2w[:2]:
            st.append({'t':'translate','k':'Перевод','q':'«'+ru+'»','answer':[d],'ph':'…'})
        # впиши слово по памяти — подсказка: первая буква (как в книге)
        for d,ru,ty in chunk:
            lm=bare(d);v=vet_pick(lm,ci+13)
            if v and v['nl'] not in usedNl:
                q=re.sub(r'\b'+re.escape(lm)+r'\b','___',v['nl'],count=1)
                if q!=v['nl']:
                    st.append({'t':'gapType','k':'Впиши по памяти','q':q,'answer':[lm],'ph':lm[0]+'…','hint':'Первая буква: «'+lm[0]+'» · '+v['ru']})
                    usedNl.add(v['nl']);break
        spoken=0
        for d,ru,ty in (p2w+p1w):
            if d.startswith(('de ','het ','een ')) and spoken<2:
                st.append({'t':'speak','k':'Говорение','phrase':'Dit is '+d+'.','tr':'Это '+ru+'.'})
                spoken+=1
        qa_pool=[q for q in QA if q['theme']==ti] or QA
        if qa_pool:
            q=qa_pool[(ci+n)%len(qa_pool)]
            others=[x['a_nl'] for x in QA if x['a_nl']!=q['a_nl']][(n*3)%(len(QA)-4):][:3]
            st.append({'t':'listen','k':'Вопрос на слух','audio':q['q_nl'],'q':'Тебя спросили: … Что прозвучало?','opts':[q['q_nl']]+[x['q_nl'] for x in QA if x['q_nl']!=q['q_nl']][(n*5)%(len(QA)-4):][:3]})
            st.append({'t':'quiz','k':'Твой ответ','q':'«'+q['q_nl']+'» — что ответишь?','opts':[q['a_nl']]+others})
            st.append({'t':'speak','k':'Говорение','phrase':q['a_nl'],'tr':q['a_ru']})
        mix=[ [d,ru] for d,ru,ty in (p1w[2:4]+p2w[2:4]) ]
        if len(mix)>=3: st.append({'t':'match','k':'Пары · всё вместе','pairs':mix[:4]})
        parts.append({'t':'Говорим и закрепляем','steps':st})
        lessons[str(n)]={'parts':parts}
    themeLessons[str(ti)]=nums

json.dump({'themes':[{'t':name,'w':[[d,ru] for d,ru,ty in ws]} for name,ws in BANK]},
 open(ROOT+'/data/bank.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
json.dump({'note':'Автоуроки тем 3–8 (39–79), сгенерированы make_data из банка 5000 + vetted_translations. Схема: meta[{n,t,blk}], themeLessons{ti:[n]}, lessons{n:{parts:[{t,steps[]}]}}.',
 'meta':meta,'themeLessons':themeLessons,'lessons':lessons},
 open(ROOT+'/data/lessons_generated.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print("bank.json themes:",len(BANK),"| lessons:",len(lessons),"| meta:",len(meta))

# Диалоги и истории живут в data/dialogues.json и data/stories.json (рукописные, make_data их НЕ трогает)
