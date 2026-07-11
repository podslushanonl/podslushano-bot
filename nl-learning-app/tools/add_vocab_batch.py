# -*- coding: utf-8 -*-
"""Батч лексики: практичные слова для A1 (append) и A2 (new_themes .w).
make_data дедупит по лемме — повторы отсеются сами. Идемпотентно."""
import json,os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

A1={
'Знакомство':[
 ['verliefd','влюблённый'],['gescheiden','разведённый'],['de partner','партнёр'],['de kennis','знакомый'],
 ['eerlijk','честный'],['beleefd','вежливый'],['verlegen','застенчивый'],['geduldig','терпеливый'],
 ['nieuwsgierig','любопытный'],['trots','гордый'],['jaloers','ревнивый'],['zenuwachtig','нервный'],
 ['streng','строгий'],['gastvrij','гостеприимный'],['behulpzaam','отзывчивый'],['de vriendschap','дружба'],
 ['de leeftijd','возраст'],['de geboortedag','день рождения'],['de voornaam','имя'],['de achternaam','фамилия'],
 ['ongetrouwd','неженатый'],['de zwangerschap','беременность'],['zwanger','беременная'],['het karakter','характер'],
],
'Каждый день':[
 ['opstaan','вставать'],['wakker worden','просыпаться'],['zich aankleden','одеваться'],['zich wassen','умываться'],
 ['ontbijten','завтракать'],['afwassen','мыть посуду'],['stofzuigen','пылесосить'],['opruimen','убираться'],
 ['strijken','гладить'],['de boodschappen','покупки (продукты)'],['de vuilnis','мусор'],['de agenda','ежедневник'],
 ['de gewoonte','привычка'],['moe','усталый'],['vroeg','рано'],['de wekker','будильник'],
 ['zich haasten','торопиться'],['op tijd','вовремя'],['de routine','распорядок'],['rustig aan','не спеша'],
 ['de vrije dag','выходной'],['bijna','почти'],['meestal','обычно'],['soms','иногда'],
],
'Школа':[
 ['het rooster','расписание'],['het huiswerk','домашнее задание'],['de toets','контрольная'],['het cijfer','оценка'],
 ['slagen','сдать (экзамен)'],['zakken','провалить (экзамен)'],['de uitleg','объяснение'],['het voorbeeld','пример'],
 ['de fout','ошибка'],['verbeteren','исправлять'],['oefenen','упражняться'],['herhalen','повторять'],
 ['begrijpen','понимать'],['uitleggen','объяснять'],['het onderwerp','тема'],['de zin','предложение'],
 ['het hoofdstuk','глава'],['de aandacht','внимание'],['concentreren','концентрироваться'],['de vooruitgang','прогресс'],
 ['het niveau','уровень'],['de opdracht','задание'],['de deelnemer','участник'],['aanwezig','присутствующий'],
],
'Еда и напитки':[
 ['het recept','рецепт'],['de maaltijd','приём пищи'],['bakken','жарить/печь'],['braden','жарить (мясо)'],
 ['proeven','пробовать (на вкус)'],['zoet','сладкий'],['zuur','кислый'],['zout','солёный'],
 ['bitter','горький'],['vers','свежий'],['bederven','портиться'],['de kruiden','приправы/травы'],
 ['de knoflook','чеснок'],['de peper','перец'],['de saus','соус'],['de olie','масло (растительное)'],
 ['het bakje','контейнер'],['de portie','порция'],['de smaak','вкус'],['honger hebben','быть голодным'],
 ['dorst hebben','хотеть пить'],['het gerecht','блюдо'],['het bijgerecht','гарнир'],['opwarmen','разогревать'],
],
'Здоровье':[
 ['de gezondheid','здоровье'],['de klacht','жалоба (на здоровье)'],['de bloeddruk','давление'],['de allergie','аллергия'],
 ['de wond','рана'],['de pleister','пластырь'],['zwellen','опухать'],['duizelig','голова кружится'],
 ['misselijk','тошнит'],['de hoofdpijn','головная боль'],['de buikpijn','боль в животе'],['de rugpijn','боль в спине'],
 ['gezond','здоровый'],['ongezond','нездоровый'],['bewegen','двигаться'],['uitrusten','отдыхать'],
 ['de spoedeisende hulp','неотложная помощь'],['de verzekering','страховка'],['de behandeling','лечение'],['genezen','вылечиться'],
 ['de operatie','операция'],['de spuit','укол'],['de temperatuur','температура'],['de leefstijl','образ жизни'],
],
'Одежда':[
 ['de stof','ткань'],['katoen','хлопок'],['wol','шерсть'],['leer','кожа'],
 ['de mouw','рукав'],['de kraag','воротник'],['de zak','карман'],['de rits','молния (застёжка)'],
 ['aantrekken','надевать'],['uittrekken','снимать (одежду)'],['de omkleedkamer','раздевалка'],['de korting','скидка'],
 ['de uitverkoop','распродажа'],['strak','обтягивающий'],['los','свободный (об одежде)'],['comfortabel','удобный'],
 ['de mode','мода'],['modern','современный'],['ouderwets','старомодный'],['schoon','чистый'],
 ['de vlek','пятно'],['de knoop','пуговица'],['de riem','ремень'],['de veter','шнурок'],
],
'Путешествия':[
 ['de bestemming','пункт назначения'],['de reservering','бронирование'],['reserveren','бронировать'],['annuleren','отменять'],
 ['de vertraging','задержка'],['de aankomst','прибытие'],['het vertrek','отправление'],['overstappen','делать пересадку'],
 ['de route','маршрут'],['de omweg','объезд'],['de grens','граница'],['het buitenland','заграница'],
 ['de bagage','багаж'],['de koffer','чемодан'],['inpakken','упаковывать'],['uitpakken','распаковывать'],
 ['de rugzak','рюкзак'],['het paspoort','паспорт'],['de verzekering','страховка'],['het uitzicht','вид'],
 ['de toerist','турист'],['bezoeken','посещать'],['de omgeving','окрестности'],['onderweg','в пути'],
],
'Досуг':[
 ['de hobby','хобби'],['het tijdverdrijf','времяпрепровождение'],['tekenen','рисовать'],['schilderen','писать красками'],
 ['fotograferen','фотографировать'],['tuinieren','заниматься садом'],['wandelen','гулять'],['fietsen','кататься на велосипеде'],
 ['de wedstrijd','соревнование'],['de ploeg','команда'],['winnen','выигрывать'],['verliezen','проигрывать'],
 ['het lidmaatschap','членство'],['de vereniging','клуб/объединение'],['het optreden','выступление'],['het concert','концерт'],
 ['de tentoonstelling','выставка'],['de voorstelling','представление'],['gezellig','уютный/приятный'],['ontspannen','расслабляться'],
 ['de vrijetijd','досуг'],['het pretpark','парк развлечений'],['het bordspel','настольная игра'],['verzamelen','коллекционировать'],
],
'Жильё':[
 ['de woning','жильё'],['de verhuizing','переезд'],['de huur','аренда'],['de hypotheek','ипотека'],
 ['de verwarming','отопление'],['de airco','кондиционер'],['het stopcontact','розетка'],['de zekering','предохранитель'],
 ['de kraan','кран'],['de wastafel','раковина'],['het gordijn','штора'],['het tapijt','ковёр'],
 ['de zolder','чердак'],['de kelder','подвал'],['het balkon','балкон'],['de berging','кладовка'],
 ['de buren','соседи'],['de overlast','беспокойство/шум'],['schoonmaken','убирать'],['repareren','чинить'],
 ['de huisbaas','арендодатель'],['het contract','договор'],['de energierekening','счёт за энергию'],['gemeubileerd','меблированный'],
],
'Работа':[
 ['de baan','работа (место)'],['het beroep','профессия'],['de werkervaring','опыт работы'],['de collega','коллега'],
 ['de chef','начальник'],['het salaris','зарплата'],['de pauze','перерыв'],['overwerken','перерабатывать'],
 ['de dienst','смена'],['het rooster','график'],['de vakantie','отпуск'],['ziekmelden','брать больничный'],
 ['solliciteren','устраиваться на работу'],['het sollicitatiegesprek','собеседование'],['de vacature','вакансия'],['aannemen','нанимать'],
 ['ontslaan','увольнять'],['de werkplek','рабочее место'],['de veiligheid','безопасность'],['het gereedschap','инструменты'],
 ['de deadline','срок сдачи'],['de vergadering','совещание'],['afspreken','договариваться'],['de taak','задача'],
],
}

A2={
'Переезд':[
 ['de inschrijving','регистрация'],['inschrijven','регистрироваться'],['het adres','адрес'],['de nutsvoorzieningen','коммунальные услуги'],
 ['de aansluiting','подключение'],['de meterstand','показания счётчика'],['de vloer','пол'],['de verhuiswagen','фургон для переезда'],
 ['tillen','поднимать'],['de doos','коробка'],['inrichten','обустраивать'],['de buurt','район'],
],
'Нидерланды':[
 ['de polder','польдер'],['de dijk','дамба'],['het kanaal','канал'],['de molen','мельница'],
 ['de koning','король'],['de provincie','провинция'],['de vlag','флаг'],['het volkslied','гимн'],
 ['de gewoonte','обычай'],['de feestdag','праздник'],['typisch','типичный'],['de traditie','традиция'],
],
'Дети':[
 ['de opvoeding','воспитание'],['de luier','подгузник'],['de kinderwagen','коляска'],['de crèche','ясли'],
 ['de oppas','няня'],['de peuter','малыш (2-4)'],['de tiener','подросток'],['opvoeden','воспитывать'],
 ['de zakgeld','карманные деньги'],['de regels','правила'],['belonen','поощрять'],['straffen','наказывать'],
],
'Магазины':[
 ['de aanbieding','акция/предложение'],['de bon','чек'],['ruilen','обменять'],['de garantie','гарантия'],
 ['de kassa','касса'],['contant','наличными'],['pinnen','платить картой'],['de winkelwagen','тележка'],
 ['de verkoper','продавец'],['het merk','бренд'],['de maat','размер'],['tweedehands','подержанный'],
],
'Образование':[
 ['de opleiding','образование/курс'],['het diploma','диплом'],['de studie','учёба'],['de student','студент'],
 ['het examen','экзамен'],['de inburgering','интеграция'],['het taalniveau','уровень языка'],['de cursus','курс'],
 ['inschrijven','записаться'],['het collegegeld','плата за обучение'],['de aanwezigheid','посещаемость'],['afstuderen','окончить учёбу'],
],
'Поиск работы':[
 ['de vacature','вакансия'],['het cv','резюме'],['de motivatiebrief','мотивационное письмо'],['de referentie','рекомендация'],
 ['het uitzendbureau','кадровое агентство'],['de proeftijd','испытательный срок'],['het contract','контракт'],['het netwerk','связи'],
 ['de vaardigheid','навык'],['geschikt','подходящий'],['de ervaring','опыт'],['solliciteren','подавать заявку'],
],
'На работе':[
 ['de werkgever','работодатель'],['de werknemer','работник'],['de cao','коллективный договор'],['het loonstrookje','расчётный лист'],
 ['de toeslag','надбавка'],['het pensioen','пенсия'],['de vakbond','профсоюз'],['de functie','должность'],
 ['de afdeling','отдел'],['leidinggeven','руководить'],['samenwerken','сотрудничать'],['de werkdruk','нагрузка'],
],
'Gemeente':[
 ['het loket','окошко'],['de balie','стойка'],['de ambtenaar','чиновник'],['de aanvraag','заявление'],
 ['het formulier','бланк'],['de afspraak','приём'],['de identiteitskaart','удостоверение личности'],['het uittreksel','выписка'],
 ['de legeskosten','пошлина'],['de handtekening','подпись'],['geldig','действительный'],['verlengen','продлевать'],
],
}

ex=json.load(open(ROOT+'/data/extra_words.json',encoding='utf-8'))
# A1 → append
added_a1=0
for th,ws in A1.items():
    lst=ex['append'].setdefault(th,[])
    have={w[0].split(' ')[-1].lower() for w in lst}
    for d,ru in ws:
        lm=d.split(' ')[-1].lower()
        if lm in have:continue
        have.add(lm);lst.append([d,ru]);added_a1+=1
# A2 → new_themes .w
added_a2=0
byname={t['t']:t for t in ex['new_themes']}
for th,ws in A2.items():
    t=byname.get(th)
    if not t:continue
    have={w[0].split(' ')[-1].lower() for w in t['w']}
    for d,ru in ws:
        lm=d.split(' ')[-1].lower()
        if lm in have:continue
        have.add(lm);t['w'].append([d,ru]);added_a2+=1
json.dump(ex,open(ROOT+'/data/extra_words.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(f'Добавлено (после дедупа внутри файла): A1 +{added_a1}, A2 +{added_a2}, всего +{added_a1+added_a2}')
