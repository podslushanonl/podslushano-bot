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
EMOJI_NL.update({
 'achternaam':'🪪','leeftijd':'🎂','gezin':'👪','oom':'👨','tante':'👩','gast':'🙋','tweeling':'👯',
 'wekker':'⏰','weekend':'🎉','verjaardag':'🎂','pauze':'☕','boodschappen':'🛒','huiswerk':'📚','was':'🧺','afwas':'🍽️',
 'leerling':'🧑‍🎓','student':'🧑‍🎓','juf':'👩‍🏫','meester':'👨‍🏫','directeur':'🧑‍💼','lokaal':'🏫','rooster':'📅',
 'opdracht':'📋','oefening':'✏️','fout':'❌','examen':'🎓','toets':'📝','cijfer':'🔢','diploma':'🎓','taal':'🗣️',
 'woord':'🔤','zin':'📃','letter':'🔠','map':'📁','schaar':'✂️','lijm':'🧴','schrift':'📓','laptop':'💻',
 'maaltijd':'🍽️','gerecht':'🍲','smaak':'👅','honger':'😋','dorst':'🥤','bestek':'🍴','vork':'🍴','mes':'🔪',
 'pan':'🍳','glas':'🥛','fles':'🍾','kopje':'☕','peper':'🌶️','olie':'🫒','honing':'🍯','jam':'🍓',
 'pannenkoek':'🥞','haring':'🐟','frietjes':'🍟','stroopwafel':'🧇','erwtensoep':'🍲','hagelslag':'🍫','pindakaas':'🥜',
 'huisarts':'👨‍⚕️','verpleegkundige':'👩‍⚕️','patiënt':'🤒','verzekering':'📋','hoest':'🤧','wond':'🩹','verband':'🩹',
 'pleister':'🩹','zalf':'🧴','druppel':'💧','operatie':'🏥','allergie':'🤧','dieet':'🥗','gewicht':'⚖️',
 'kleding':'👕','ondergoed':'🩲','pyjama':'🛌','blouse':'👚','overhemd':'👔','pak':'🕴️','stropdas':'👔',
 'knoop':'🔘','spijkerbroek':'👖','slipper':'🩴','veter':'👟','wol':'🧶','mode':'💃',
 'reis':'🧳','reiziger':'🧳','vertrek':'🛫','aankomst':'🛬','vertraging':'⏳','perron':'🚉','chauffeur':'🚗',
 'douane':'🛂','koffer':'🧳','rugzak':'🎒','bagage':'🧳','benzine':'⛽','tankstation':'⛽','parkeerplaats':'🅿️',
 'rotonde':'🔄','verkeer':'🚦','snelweg':'🛣️','grens':'🛂','buitenland':'🌍',
 'concert':'🎤','theater':'🎭','bioscoop':'🎬','voorstelling':'🎭','festival':'🎪','tentoonstelling':'🖼️',
 'pretpark':'🎢','dierentuin':'🦁','terras':'☕','wandeling':'🚶','picknick':'🧺','barbecue':'🍖','training':'🏋️',
 'wedstrijd':'🏆','doelpunt':'⚽','winnaar':'🥇','meer':'🏞️','rivier':'🏞️','berg':'⛰️','camping':'🏕️','tent':'⛺',
 'woning':'🏠','studio':'🏢','hypotheek':'🏦','buurt':'🏘️','wijk':'🏘️','centrum':'🏙️','uitzicht':'🌅',
 'ingang':'🚪','uitgang':'🚪','brievenbus':'📬','stopcontact':'🔌','kraan':'🚰','gordijn':'🪟','kussen':'🛏️',
 'deken':'🛌','laken':'🛏️','zeep':'🧼','shampoo':'🧴',
 'beroep':'💼','werknemer':'🧑‍💼','klant':'🛍️','overleg':'👥','project':'📊','taak':'✅','belasting':'🧾',
 'bonus':'💰','pensioen':'👴','magazijn':'📦','verhuisdoos':'📦','ladder':'🪜','gereedschap':'🧰','boor':'🛠️',
 'hamer':'🔨','schroef':'🔩','verf':'🎨','kwast':'🖌️','paraplu':'☂️','mist':'🌫️','storm':'🌪️','hagel':'🌨️',
 'hoofdstad':'🏛️','inwoner':'🙋','cultuur':'🎭','traditie':'🎎','klomp':'🥿','polder':'🌾','kanaal':'🌉','gracht':'🌉',
 'peuter':'🧒','kleuter':'🧒','tiener':'🧑','knuffel':'🧸','wieg':'👶','kinderwagen':'👶','speeltuin':'🛝',
 'schommel':'🛝','glijbaan':'🛝','oppas':'🧑‍🍼','rapport':'📄','traktatie':'🧁',
 'aanbieding':'🏷️','reclame':'📢','folder':'📄','kassabon':'🧾','garantie':'✅','winkelwagen':'🛒','mandje':'🧺',
 'weegschaal':'⚖️','etalage':'🪟','uitverkoop':'🏷️','merk':'™️',
 'universiteit':'🎓','bibliotheek':'📚','wiskunde':'➗','geschiedenis':'🏛️','aardrijkskunde':'🌍','biologie':'🧬',
 'natuurkunde':'⚛️','mentor':'🧑‍🏫','klasgenoot':'🧑‍🤝‍🧑','tentamen':'📝',
 'sollicitatiebrief':'✉️','sollicitatiegesprek':'🤝','motivatie':'🔥','vaardigheid':'🛠️','proeftijd':'⏳',
 'bijbaan':'💼','loon':'💶','kans':'🍀','eis':'📌','netwerk':'🕸️',
 'afdeling':'🏢','receptie':'🛎️','kantine':'🍽️','koffiepauze':'☕','presentatie':'📊','verslag':'📄',
 'printer':'🖨️','vergaderzaal':'👥','toetsenbord':'⌨️','muis':'🖱️','wachtwoord':'🔑','bijlage':'📎',
 'promotie':'📈','sfeer':'✨','veiligheid':'🦺','helm':'⛑️','werkkleding':'🦺',
 'gemeentehuis':'🏛️','inschrijving':'📝','inburgering':'🎓','subsidie':'💶','uitkering':'💶','huurtoeslag':'💶',
 'zorgtoeslag':'💶','kinderbijslag':'💶','grofvuil':'🗑️','brandweer':'🚒','ambulance':'🚑'})
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

def anagram_ok(lm):
    return 4<=len(lm)<=8 and lm.isalpha()

def qa_distr(cor,salt):
    """Дистракторы для «Твой ответ»: конкретные ответы из ДРУГИХ доменов,
    без Ja/Nee-начала (иначе «все варианты подходят»)."""
    cand=[x['a_nl'] for x in QA if x['a_nl']!=cor
          and not x['a_nl'].startswith(('Ja','Nee'))
          and x['a_nl'].split(' ')[0]!=cor.split(' ')[0]]
    out=[]
    for k2 in range(len(cand)):
        v=cand[(salt+k2)%len(cand)]
        if v not in out:out.append(v)
        if len(out)>=3:break
    return out

def words_html(name,ws):
    rows=''.join('<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--brd)"><b>'+d+'</b><span style="color:var(--ink-2)">'+ru+'</span></div>' for d,ru,ty in ws)
    return '<p>Новые слова темы «'+name+'». Сначала познакомься со ВСЕМИ словами — прослушай каждое (▶ ниже), потом закрепим заданиями.</p><div style="margin-top:8px">'+rows+'</div>'

for ti in range(0,len(BANK)):
    name,ws=BANK[ti]
    chunks=[ws[i:i+8] for i in range(0,len(ws),8)]
    chunks=[c for c in chunks if len(c)>=6][:12]
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
        # что означает эмодзи? (картинка → слово)
        emq=0
        for d,ru,ty in p1w:
            em=EMOJI_NL.get(bare(d))
            if em and emq<2:
                st.append({'t':'quiz','k':'Картинка','q':'Что означает '+em+'?','opts':[d]+pick_distractors(pool,d,0,3,salt=n+emq*3)})
                emq+=1
        if len(p1w)>2:
            d2,ru2,ty2=p1w[2]
            st.append({'t':'quiz','k':'Значение','q':'«'+d2+'» — это…','opts':[ru2]+pick_distractors(pool,ru2,1,3,salt=n+13)})
        # слух: слово с похожими вариантами
        d0,ru0,ty0=p1w[0]
        st.append({'t':'listen','k':'Аудирование','audio':d0,'q':'Что прозвучало?','opts':[d0]+similar_distr(pool,d0)})
        if len(p1w)>1:
            d1b,ru1b,ty1b=p1w[1]
            st.append({'t':'listen','k':'Аудирование','audio':d1b,'q':'А теперь? Варианты похожи.','opts':[d1b]+similar_distr(pool,d1b)})
        # перевод-набор (пиши сам)
        st.append({'t':'translate','k':'Перевод','q':'«'+p1w[-1][1]+'»','answer':[p1w[-1][0]],'ph':'…'})
        # анаграмма: собери слово из букв
        for d,ru,ty in p1w:
            lm=bare(d)
            if anagram_ok(lm):
                st.append({'t':'build','k':'Пазл: собери слово','tr':ru+' ('+str(len(lm))+' букв)','words':list(lm),'ans':list(lm)})
                break
        # верно/неверно
        wr1=pick_distractors(pool,p1w[0][1],1,1,salt=n+5)[0]
        st.append({'t':'tf','k':'Верно?','q':'«'+p1w[0][0]+'» значит «'+wr1+'».','answer':False,'note':'Нет: '+p1w[0][0]+' — '+p1w[0][1]+'.'})
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
        if len(p2w)>=3:
            st.append({'t':'match','k':'Пары','pairs':[[d,ru] for d,ru,ty in p2w]})
        emq2=0
        for d,ru,ty in p2w:
            em=EMOJI_NL.get(bare(d))
            if em and emq2<1:
                st.append({'t':'quiz','k':'Картинка','q':'Что означает '+em+'?','opts':[d]+pick_distractors(pool,d,0,3,salt=n+11)})
                emq2+=1
        own2=[d for d,ru,ty in p2w[:3]]
        if len(own2)>=3:
            oti2=(ti*5+ci+3)%10
            if oti2==ti:oti2=(oti2+1)%10
            ow2=BANK[oti2][1][(n*11)%len(BANK[oti2][1])]
            st.append({'t':'quiz','k':'Лишнее слово','q':'Какое слово НЕ подходит к теме «'+name+'»?','opts':[ow2[0]]+own2})
        for d,ru,ty in p2w:
            lm=bare(d)
            if anagram_ok(lm):
                st.append({'t':'build','k':'Пазл: собери слово','tr':ru+' ('+str(len(lm))+' букв)','words':list(lm),'ans':list(lm)})
                break
        st.append({'t':'translate','k':'Перевод','q':'«'+p2w[0][1]+'»','answer':[p2w[0][0]],'ph':'…'})
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
        # второй квиз «этот/тот» (deze/die)
        dm2=0
        for d,ru,ty in chunk[::-1]:
            lm=bare(d);dv=DEMV.get(lm)
            if dv and len(dv)>=2 and dm2<1:
                v=dv[(ci+1)%len(dv)]
                distr=[x['nl'] for x in dv if x['nl']!=v['nl']][:2]
                if POSSV.get(lm):distr+=[x['nl'] for x in POSSV[lm] if x['nl'] not in distr][:3-len(distr)]
                if len(distr)>=2:
                    st.append({'t':'quiz','k':'Этот, тот…','q':'Как сказать «'+v['ru']+'»?','opts':[v['nl']]+distr[:3]})
                    dm2+=1
        arts=0
        for d,ru,ty in chunk:
            if d.startswith(('de ','het ')) and arts<2:
                art=d.split(' ')[0];lmx=bare(d)
                st.append({'t':'quiz','k':'de или het?','q':'Какой артикль: ___ '+lmx+' ('+ru+')?','opts':[art,'het' if art=='de' else 'de']})
                arts+=1
        for d,ru,ty in chunk:
            pl=PLUV.get(bare(d))
            if pl:
                if (ci+n)%2==0:
                    st.append({'t':'tf','k':'Верно?','q':'Множественное число от «'+d+'» — «'+pl['nl']+'».','answer':True,'note':'Да: '+pl['nl']+'.'})
                else:
                    wrongpl=None;ii=n+3;pool_lms2=[bare(x[0]) for x in pool]
                    for _ in range(len(pool_lms2)):
                        cand=PLUV.get(pool_lms2[ii%len(pool_lms2)]);ii+=1
                        if cand and cand['nl']!=pl['nl']:wrongpl=cand['nl'];break
                    if wrongpl:
                        st.append({'t':'tf','k':'Верно?','q':'Множественное число от «'+d+'» — «'+wrongpl+'».','answer':False,'note':'Нет: '+pl['nl']+'.'})
                break
        for d,ru,ty in p1w[:2]+p2w[2:4]:
            st.append({'t':'translate','k':'Перевод','q':'«'+ru+'»','answer':[d],'ph':'…'})
        if len(st)>=5: parts.append({'t':'Формы и фразы','steps':st})
        else: parts[-1]['steps'].extend(st[1:])
        # ---------- ЧАСТЬ 4: Предложения и слух ----------
        st=[{'t':'explain','k':'Шаг 4 из 5','b':'📖 Слово в предложении','html':'<p>Теперь — целые предложения с новыми словами. Сначала собери, потом услышь и допиши.</p><div class="rule">Dit is … — это … · Waar is …? — где …? · Ik heb … — у меня есть …</div>'}]
        addedS=0;usedNl=set()
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+addedS*2+1)
            if v and addedS<4 and v['nl'] not in usedNl:
                import re as _re
                toks=_re.sub(r'[.?!]$','',v['nl']).split(' ')
                st.append({'t':'build','k':'Предложение','tr':v['ru'],'words':toks,'ans':toks})
                usedNl.add(v['nl']);addedS+=1
        ALL_NL=[x['nl'] for lst in VETL.values() for x in lst]
        sl=0
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+7)
            if v and sl<2 and len(ALL_NL)>=4 and v['nl'] not in usedNl:
                others=[x for x in ALL_NL if x!=v['nl']]
                sd=[];ii=ci*7+3
                for _ in range(len(others)):
                    cand=others[ii%len(others)];ii+=1
                    if cand not in sd:sd.append(cand)
                    if len(sd)>=3:break
                st.append({'t':'listen','k':'Аудирование','audio':v['nl'],'q':'Какое предложение прозвучало?','opts':[v['nl']]+sd})
                usedNl.add(v['nl']);sl+=1
        gp=0
        for d,ru,ty in chunk:
            lm=bare(d);v=vet_pick(lm,ci+11+gp)
            if v and gp<2 and lm in v['nl'] and v['nl'] not in usedNl:
                st.append({'t':'gapType','k':'На слух','audio':v['nl'],'q':v['nl'].replace(lm,'___',1),'answer':[lm],'ph':'…'})
                usedNl.add(v['nl']);gp+=1
        # сколько слов в предложении? (на слух, как в книге)
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+17)
            if v and v['nl'] not in usedNl:
                nw=len(v['nl'].split())
                if nw>=4:
                    st.append({'t':'quiz','k':'Сколько слов?','audio':v['nl'],'q':'Прослушай предложение. Сколько в нём слов?','opts':[str(nw),str(nw-1),str(nw+1),str(nw+2)]})
                    usedNl.add(v['nl']);break
        # диктант: запиши предложение целиком (как в книге «Wat hoor je?»)
        for d,ru,ty in chunk:
            v=vet_pick(bare(d),ci+19)
            if v and v['nl'] not in usedNl and 3<=len(v['nl'].split())<=5:
                st.append({'t':'dict','k':'Диктант','audio':v['nl'],'answer':[v['nl']],'tr':v['ru']})
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
        # второй Vul in — ещё 3 предложения
        cb2=[]
        for d,ru,ty in list(chunk)+[w for w in ws if w not in chunk]:
            if len(cb2)>=3:break
            lm=bare(d)
            if lm in cb_l:continue
            v=vet_pick(lm,ci*7+9)
            if not v or v['nl'] in usedNl:continue
            q2=re.sub(r'\b'+re.escape(lm)+r'\b','___',v['nl'],count=1)
            if q2==v['nl']:continue
            cb2.append([q2,lm,v['ru']]);cb_l.add(lm);usedNl.add(v['nl'])
        if len(cb2)==3:
            extra2=None
            for k2 in range(len(pool)):
                lmx=bare(pool[(n*3+k2)%len(pool)][0])
                if lmx not in cb_l:extra2=lmx;break
            if extra2:
                st.append({'t':'clozeBank','k':'Vul in · раунд 2','sents':cb2,'bank':[c[1] for c in cb2]+[extra2]})
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
        # слух-повторение слова из части 1
        dL,ruL,tyL=p1w[min(2,len(p1w)-1)]
        st.append({'t':'listen','k':'Повторение на слух','audio':dL,'q':'Что прозвучало?','opts':[dL]+similar_distr(pool,dL)})
        spoken=0
        for d,ru,ty in (p2w+p1w):
            if d.startswith(('de ','het ','een ')) and spoken<3:
                st.append({'t':'speak','k':'Говорение','phrase':'Dit is '+d+'.','tr':'Это '+ru+'.'})
                spoken+=1
        qa_pool=[q for q in QA if q['theme']==ti] or QA
        if qa_pool:
            q=qa_pool[(ci+n)%len(qa_pool)]
            st.append({'t':'listen','k':'Вопрос на слух','audio':q['q_nl'],'q':'Тебя спросили: … Что прозвучало?','opts':[q['q_nl']]+[x['q_nl'] for x in QA if x['q_nl']!=q['q_nl']][(n*5)%(len(QA)-4):][:3]})
            st.append({'t':'quiz','k':'Твой ответ','q':'Тебя спрашивают: «'+q['q_nl']+'» ('+q['q_ru']+'). Что ответишь?','opts':[q['a_nl']]+qa_distr(q['a_nl'],n*3)})
            st.append({'t':'speak','k':'Говорение','phrase':q['a_nl'],'tr':q['a_ru']})
            q2=qa_pool[(ci+n+3)%len(qa_pool)]
            if q2['q_nl']!=q['q_nl']:
                st.append({'t':'quiz','k':'Твой ответ','q':'«'+q2['q_nl']+'» ('+q2['q_ru']+'). Что ответишь?','opts':[q2['a_nl']]+qa_distr(q2['a_nl'],n*5+7)})
        # диктант в финал
        for d,ru,ty in p1w:
            v=vet_pick(bare(d),ci+23)
            if v and v['nl'] not in usedNl and 3<=len(v['nl'].split())<=6:
                st.append({'t':'dict','k':'Диктант','audio':v['nl'],'answer':[v['nl']],'tr':v['ru']})
                usedNl.add(v['nl']);break
        for d,ru,ty in p1w[::-1]:
            lm=bare(d)
            if anagram_ok(lm):
                st.append({'t':'build','k':'Пазл: собери слово','tr':ru+' ('+str(len(lm))+' букв)','words':list(lm),'ans':list(lm)})
                break
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
