/* Q4 /ads translation overlay.
   The base i18n.js owns the RU / NL / EN switcher. This file adds translations
   for the current Q4 landing page, gift flow and checkout without changing
   booking payloads or product identifiers. */
(() => {
  "use strict";

  const SUPPORTED = ["ru", "nl", "en"];
  const translations = {
    "Форматы": ["Formaten", "Formats"],
    "Как работаем": ["Zo werken we", "How it works"],
    "Вопросы": ["Vragen", "Questions"],
    "Выбрать рекламу": ["Advertentie kiezen", "Choose advertising"],
    "Набор рекламодателей · октябрь — декабрь 2026": ["Advertentieplaatsen · oktober — december 2026", "Advertising availability · October — December 2026"],
    "Реклама в Podslushano.nl": ["Adverteren bij Podslushano.nl", "Advertising with Podslushano.nl"],
    "Покажите себя аудитории, которая живёт в Нидерландах.": ["Bereik een doelgroep die in Nederland woont.", "Reach an audience that lives in the Netherlands."],
    "От одного рекламного выхода до полноценной кампании. Вы выбираете задачу — мы адаптируем подачу под русскоязычную аудиторию Нидерландов и редакционный стиль Podslushano.nl.": ["Van één advertentieplaatsing tot een volledige campagne. U kiest het doel — wij stemmen de boodschap af op de Russischtalige doelgroep in Nederland en de redactionele stijl van Podslushano.nl.", "From a single advertising placement to a full campaign. You choose the goal — we adapt the message to the Russian-speaking audience in the Netherlands and the editorial style of Podslushano.nl."],
    "Рекламные форматы для бизнеса, экспертов и проектов в Нидерландах. Выберите задачу — мы подготовим подачу и размещение.": ["Advertentieformaten voor bedrijven, experts en projecten in Nederland. Kies uw doel — wij verzorgen de boodschap en plaatsing.", "Advertising formats for businesses, experts and projects in the Netherlands. Choose your goal — we prepare the message and placement."],
    "Посмотреть форматы →": ["Formaten bekijken →", "View formats →"],
    "Получить −26%": ["−26% ontvangen", "Get −26%"],
    "Забрать −26%": ["−26% activeren", "Activate −26%"],
    "−26% активна ✓": ["−26% actief ✓", "−26% active ✓"],
    "Сезонное предложение": ["Seizoensaanbod", "Seasonal offer"],
    "Осень, декабрь и время планировать рекламу заранее.": ["Najaar, december — hét moment om uw advertenties vooruit te plannen.", "Autumn, December — a good time to plan your advertising ahead."],
    "Подпишитесь на редкие обновления для рекламодателей — и получите специальную цену на рекламные форматы до конца 2026 года.": ["Meld u aan voor onze sporadische updates voor adverteerders en ontvang een speciale prijs op advertentieformaten tot eind 2026.", "Subscribe to occasional advertiser updates and receive special pricing on advertising formats through the end of 2026."],
    "на рекламные форматы после подписки на обновления": ["op advertentieformaten na inschrijving voor updates", "on advertising formats after subscribing to updates"],
    "просмотров / месяц": ["weergaven / maand", "views / month"],
    "Актуальные показатели площадок Podslushano.nl. Охваты отдельных публикаций зависят от темы и алгоритмов платформ.": ["Actuele cijfers van de Podslushano.nl-kanalen. Het bereik van afzonderlijke publicaties hangt af van het onderwerp en de platformalgoritmen.", "Current Podslushano.nl platform figures. Reach for individual publications depends on the topic and platform algorithms."],
    "Как проходит размещение.": ["Zo verloopt een plaatsing.", "How a placement works."],
    "Реклама — не просто «выложить пост».": ["Adverteren is meer dan alleen ‘een post plaatsen’.", "Advertising is more than simply ‘posting something’."],
    "Мы приводим материал к редакционному виду Podslushano.nl: убираем рекламный канцелярит, находим понятный заход, собираем CTA и проверяем, чтобы читателю сразу было ясно, что ему предлагают.": ["Wij brengen uw materiaal in de redactionele stijl van Podslushano.nl: helder, natuurlijk en met een duidelijke CTA, zodat de lezer meteen begrijpt wat u aanbiedt.", "We adapt your material to Podslushano.nl’s editorial style: clear, natural and with a strong CTA, so readers immediately understand what you offer."],
    "Вы выбираете формат и дату. Мы адаптируем материал под площадку и после оплаты фиксируем слот.": ["U kiest het formaat en de datum. Wij passen het materiaal aan het platform aan en leggen het tijdslot na betaling vast.", "You choose the format and date. We adapt the material to the platform and secure the slot after payment."],
    "Вы выбираете задачу": ["U kiest het doel", "You choose the goal"],
    "Один запуск, Telegram, экспертная встреча, регулярное присутствие или кампания под ключ.": ["Eén lancering, Telegram, een expertsessie, structurele zichtbaarheid of een volledig verzorgde campagne.", "A single launch, Telegram, an expert session, ongoing visibility or a full-service campaign."],
    "Мы адаптируем подачу": ["Wij passen de boodschap aan", "We adapt the message"],
    "Текст, структура и формат публикации подстраиваются под площадку и аудиторию.": ["Tekst, structuur en publicatievorm worden afgestemd op het platform en de doelgroep.", "Copy, structure and publication format are adapted to the platform and audience."],
    "Фиксируем дату после оплаты": ["Datum vast na betaling", "Date secured after payment"],
    "Свободный слот выбирается в календаре. После Mollie дата закрепляется за рекламодателем.": ["U kiest een beschikbaar tijdslot in de kalender. Na betaling via Mollie wordt de datum voor u vastgelegd.", "Choose an available slot in the calendar. After payment through Mollie, the date is secured for you."],
    "Q4 · специальная цена": ["Q4 · speciale prijs", "Q4 · special price"],
    "−26% за подписку на обновления.": ["−26% na inschrijving voor updates.", "−26% for subscribing to updates."],
    "Не чаще одного письма в месяц — новые форматы, сезонные возможности и важные обновления по рекламе Podslushano.nl. Скидка действует на рекламные форматы до 31 декабря 2026 года; Contact Guide остаётся отдельным продуктом.": ["Maximaal één e-mail per maand met nieuwe formaten, seizoenskansen en belangrijke advertentie-updates van Podslushano.nl. De korting geldt op advertentieformaten tot en met 31 december 2026; Contact Guide blijft een apart product.", "No more than one email per month with new formats, seasonal opportunities and important Podslushano.nl advertising updates. The discount applies to advertising formats through December 31, 2026; Contact Guide remains a separate product."],
    "Открыть подарок 🎁": ["Cadeau openen 🎁", "Open gift 🎁"],
    "Рекламные форматы": ["Advertentieformaten", "Advertising formats"],
    "Выберите по задаче.": ["Kies wat bij uw doel past.", "Choose based on your goal."],
    "Карточки не растянуты искусственно: короткий формат остаётся коротким, а кампания под ключ показывает весь объём работы. Все цены уже включают 21% BTW.": ["Kies alleen wat u nodig hebt: een kort formaat blijft compact en bij een volledige campagne ziet u precies wat is inbegrepen. Alle prijzen zijn inclusief 21% btw.", "Choose only what you need: short formats stay compact, while the full-service campaign shows the complete scope. All prices include 21% VAT."],
    "Все цены уже включают 21% BTW.": ["Alle prijzen zijn inclusief 21% btw.", "All prices include 21% VAT."],
    "Один конкретный повод": ["Eén concreet moment", "One specific occasion"],
    "Рекламный выход": ["Advertentieplaatsing", "Advertising placement"],
    "Когда подходит:": ["Geschikt wanneer:", "Best for:"],
    "мероприятие, акция, запуск, открытие, новая услуга или предложение с конкретной датой.": ["u een evenement, actie, lancering, opening, nieuwe dienst of tijdgebonden aanbod wilt promoten.", "you have an event, promotion, launch, opening, new service or time-sensitive offer."],
    "Что делаем мы": ["Wat wij doen", "What we do"],
    "Адаптируем подачу под Podslushano.nl и выпускаем рекламу в выбранный день.": ["Wij passen de boodschap aan Podslushano.nl aan en publiceren de advertentie op de gekozen dag.", "We adapt the message for Podslushano.nl and publish the advertisement on your chosen day."],
    "1 основная публикация Instagram": ["1 hoofdpublicatie op Instagram", "1 main Instagram publication"],
    "2 Stories": ["2 Stories", "2 Stories"],
    "Текст, заголовок, структура и CTA": ["Tekst, kop, structuur en CTA", "Copy, headline, structure and CTA"],
    "Одна выбранная дата": ["Eén gekozen datum", "One selected date"],
    "Отдельно для Telegram": ["Alleen voor Telegram", "Telegram only"],
    "нужен нативный выход прямо в Telegram без Instagram и Stories.": ["u een native plaatsing rechtstreeks op Telegram wilt, zonder Instagram of Stories.", "you want a native placement directly on Telegram without Instagram or Stories."],
    "Главное": ["Belangrijkste", "Key point"],
    "Публикация остаётся отдельным рекламным материалом и закрепляется в канале на 7 дней.": ["De publicatie staat als afzonderlijk advertentiemateriaal in het kanaal en wordt 7 dagen vastgezet.", "The publication remains a standalone advertising post and is pinned in the channel for 7 days."],
    "1 публикация в Telegram-канале": ["1 publicatie in het Telegram-kanaal", "1 publication in the Telegram channel"],
    "Редакционная адаптация текста и CTA": ["Redactionele aanpassing van tekst en CTA", "Editorial adaptation of copy and CTA"],
    "Проверка ссылок и контактов": ["Controle van links en contactgegevens", "Link and contact check"],
    "Закрепление на 7 дней": ["7 dagen vastgezet", "Pinned for 7 days"],
    "Для экспертов и специалистов": ["Voor experts en professionals", "For experts and professionals"],
    "Экспертный эфир": ["Expertsessie", "Expert live session"],
    "хотите не просто рассказать о себе, а показать экспертизу в прямом разговоре с аудиторией.": ["u niet alleen over uzelf wilt vertellen, maar uw expertise live aan de doelgroep wilt laten zien.", "you want to demonstrate your expertise in a live conversation with the audience, not just introduce yourself."],
    "Как это работает": ["Zo werkt het", "How it works"],
    "Мы анонсируем тему и проводим Zoom Q&A, куда подписчики могут подключиться и задать вопросы эксперту напрямую.": ["Wij kondigen het onderwerp aan en organiseren een Zoom Q&A waar volgers rechtstreeks vragen aan de expert kunnen stellen.", "We announce the topic and host a Zoom Q&A where followers can join and ask the expert questions directly."],
    "1 анонс-публикация Instagram": ["1 aankondigingspublicatie op Instagram", "1 Instagram announcement publication"],
    "2 Stories для набора участников": ["2 Stories om deelnemers te werven", "2 Stories to attract participants"],
    "Подготовка темы и анонса": ["Voorbereiding van onderwerp en aankondiging", "Topic and announcement preparation"],
    "Zoom Q&A до 60 минут": ["Zoom Q&A tot 60 minuten", "Zoom Q&A up to 60 minutes"],
    "Последовательное присутствие": ["Herhaalde zichtbaarheid", "Ongoing visibility"],
    "Продвижение": ["Promotie", "Promotion"],
    "аудитория должна увидеть вас несколько раз, а не встретить один рекламный пост и забыть.": ["u meerdere keren zichtbaar wilt zijn in plaats van één advertentie te plaatsen die snel wordt vergeten.", "you want the audience to see you several times rather than encounter one ad and forget it."],
    "Главное отличие": ["Het verschil", "Key difference"],
    "Вы предоставляете исходные материалы, мы собираем из них четыре разные рекламные подачи в течение 60 дней.": ["U levert het bronmateriaal aan; wij maken er vier verschillende advertentie-uitingen van verspreid over 60 dagen.", "You provide the source material; we turn it into four different advertising angles over 60 days."],
    "4 публикации Instagram за 60 дней": ["4 Instagram-publicaties in 60 dagen", "4 Instagram publications over 60 days"],
    "8 Stories — по 2 к каждому выходу": ["8 Stories — 2 bij elke plaatsing", "8 Stories — 2 with each placement"],
    "4 разные темы / угла подачи": ["4 verschillende thema’s / invalshoeken", "4 different topics / angles"],
    "Закрепление 1 поста или Reel на 3 дня": ["1 post of Reel 3 dagen vastgezet", "1 post or Reel pinned for 3 days"],
    "Без Telegram": ["Zonder Telegram", "No Telegram"],
    "Когда рекламу нужно сделать за вас": ["Wanneer u de campagne aan ons wilt overlaten", "When you want us to build the campaign for you"],
    "Под ключ": ["Volledig verzorgd", "Full-service campaign"],
    "у вас есть продукт или услуга, но вы не хотите самостоятельно придумывать кампанию, тексты, визуалы и последовательность выходов.": ["u een product of dienst hebt, maar de campagne, teksten, visuals en planning niet zelf wilt uitwerken.", "you have a product or service but do not want to create the campaign, copy, visuals and publication sequence yourself."],
    "Что меняется": ["Wat u krijgt", "What changes"],
    "Мы начинаем с задачи и сами создаём рекламную концепцию и материалы кампании.": ["We beginnen bij uw doel en ontwikkelen zelf het advertentieconcept en de campagnematerialen.", "We start with your goal and create the advertising concept and campaign materials ourselves."],
    "Мини-бриф и рекламная концепция": ["Mini-briefing en advertentieconcept", "Mini brief and advertising concept"],
    "3 разных Instagram-материала": ["3 verschillende Instagram-contentitems", "3 different Instagram content pieces"],
    "Минимум 1 Reel при наличии видео": ["Minimaal 1 Reel als videomateriaal beschikbaar is", "At least 1 Reel when video material is available"],
    "6 Stories": ["6 Stories", "6 Stories"],
    "2 Telegram-публикации": ["2 Telegram-publicaties", "2 Telegram publications"],
    "Тексты, визуалы, базовый дизайн и монтаж": ["Teksten, visuals, basisdesign en montage", "Copy, visuals, basic design and editing"],
    "Закрепление 1 публикации на 3 дня": ["1 publicatie 3 dagen vastgezet", "1 publication pinned for 3 days"],
    "Contact Guide Premium на 2 месяца": ["Contact Guide Premium voor 2 maanden", "Contact Guide Premium for 2 months"],
    "Корректировка после первой волны": ["Bijsturing na de eerste ronde", "Adjustment after the first wave"],
    "Итоговая статистика": ["Eindstatistieken", "Final performance statistics"],
    "Сравнение": ["Vergelijking", "Comparison"],
    "В чём разница.": ["Wat is het verschil?", "What’s the difference?"],
    "Не нужно покупать большой пакет ради одной задачи. Выберите площадку и глубину работы, которые подходят именно вашему запуску.": ["U hoeft geen groot pakket te kopen voor één doel. Kies het kanaal en de omvang die bij uw campagne passen.", "You do not need a large package for one objective. Choose the channel and level of support that fit your campaign."],
    "Задача": ["Onderdeel", "Feature"],
    "Выход €99": ["Plaatsing €99", "Placement €99"],
    "Эфир €120": ["Expertsessie €120", "Expert session €120"],
    "Под ключ €299": ["Volledig verzorgd €299", "Full-service €299"],
    "Срок / дата": ["Looptijd / datum", "Period / date"],
    "1 дата": ["1 datum", "1 date"],
    "1 дата эфира": ["1 sessiedatum", "1 session date"],
    "60 дней": ["60 dagen", "60 days"],
    "кампания": ["campagne", "campaign"],
    "1 публикация": ["1 publicatie", "1 publication"],
    "1 анонс": ["1 aankondiging", "1 announcement"],
    "4 публикации": ["4 publicaties", "4 publications"],
    "3 материала": ["3 contentitems", "3 content pieces"],
    "2 публикации": ["2 publicaties", "2 publications"],
    "Живой формат": ["Live formaat", "Live format"],
    "Создание материалов": ["Contentcreatie", "Content creation"],
    "адаптация": ["aanpassing", "adaptation"],
    "анонс + организация": ["aankondiging + organisatie", "announcement + organisation"],
    "адаптация ваших материалов": ["aanpassing van uw materiaal", "adaptation of your materials"],
    "концепция + создание нами": ["concept + creatie door ons", "concept + creation by us"],
    "Premium / 2 месяца": ["Premium / 2 maanden", "Premium / 2 months"],
    "Отдельный продукт": ["Apart product", "Separate product"],
    "Карточка специалиста или бизнеса в поиске нашего Telegram-бота. Contact Guide не участвует в сезонной скидке −26%. В формате «Под ключ» Premium уже включён на 2 месяца.": ["Een profiel van een professional of bedrijf in de zoekfunctie van onze Telegram-bot. Contact Guide valt niet onder de seizoenskorting van −26%. Bij ‘Volledig verzorgd’ is Premium al 2 maanden inbegrepen.", "A professional or business listing in our Telegram bot search. Contact Guide is not included in the −26% seasonal discount. The Full-service campaign already includes Premium for 2 months."],
    "Добавить себя в Contact Guide →": ["Toevoegen aan Contact Guide →", "Add yourself to Contact Guide →"],
    "1 месяц · обычная позиция": ["1 maand · standaardpositie", "1 month · standard position"],
    "€99 / год": ["€99 / jaar", "€99 / year"],
    "1 месяц · фото/логотип · бейдж 🌟 · выше Standard": ["1 maand · foto/logo · badge 🌟 · boven Standard", "1 month · photo/logo · badge 🌟 · above Standard"],
    "€109 / 6 мес · €199 / год": ["€109 / 6 mnd · €199 / jaar", "€109 / 6 months · €199 / year"],
    "Цены уже с BTW?": ["Zijn de prijzen inclusief btw?", "Do prices include VAT?"],
    "Да. На рекламной странице указан итог с 21% BTW.": ["Ja. Alle prijzen op de advertentiepagina zijn inclusief 21% btw.", "Yes. All prices on the advertising page include 21% VAT."],
    "Как получить скидку −26%?": ["Hoe krijg ik de −26% korting?", "How do I get the −26% discount?"],
    "Нажмите на подарок, оставьте e-mail и подтвердите подписку на обновления для рекламодателей. После этого сезонная цена автоматически появится на всех рекламных форматах. Предложение действует до 31 декабря 2026 года и не распространяется на отдельные тарифы Contact Guide.": ["Open het cadeau, vul uw e-mailadres in en bevestig uw inschrijving voor updates voor adverteerders. Daarna verschijnen de seizoensprijzen automatisch bij alle advertentieformaten. Het aanbod geldt tot en met 31 december 2026 en niet voor losse Contact Guide-tarieven.", "Open the gift, enter your email and confirm your subscription to advertiser updates. Seasonal prices will then appear automatically for all advertising formats. The offer is valid through December 31, 2026 and does not apply to standalone Contact Guide plans."],
    "Что такое «Экспертный эфир»?": ["Wat is een ‘Expertsessie’?", "What is an ‘Expert live session’?"],
    "Это анонс + онлайн Zoom Q&A с аудиторией Podslushano.nl. Подписчики подключаются к встрече и задают эксперту вопросы по его теме напрямую.": ["Dit is een aankondiging plus een online Zoom Q&A met de doelgroep van Podslushano.nl. Volgers kunnen deelnemen en rechtstreeks vragen stellen aan de expert.", "It is an announcement plus an online Zoom Q&A with the Podslushano.nl audience. Followers join the session and ask the expert questions directly."],
    "Когда бронируется дата?": ["Wanneer is de datum gereserveerd?", "When is the date booked?"],
    "Дата считается забронированной после успешной оплаты Mollie.": ["De datum is gereserveerd zodra de betaling via Mollie is geslaagd.", "The date is booked after successful payment through Mollie."],
    "Можно гарантировать продажи?": ["Kunnen jullie verkopen garanderen?", "Can you guarantee sales?"],
    "Нет. Мы гарантируем согласованный объём нашей работы и размещений, но не конкретное число продаж, заявок или подписчиков.": ["Nee. Wij garanderen de afgesproken werkzaamheden en plaatsingen, maar geen specifiek aantal verkopen, aanvragen of volgers.", "No. We guarantee the agreed scope of work and placements, but not a specific number of sales, enquiries or followers."],
    "Podslushano.nl · реклама для русскоязычной аудитории Нидерландов": ["Podslushano.nl · adverteren voor de Russischtalige doelgroep in Nederland", "Podslushano.nl · advertising to the Russian-speaking audience in the Netherlands"],
    "Все цены incl. BTW 21%": ["Alle prijzen incl. 21% btw", "All prices incl. 21% VAT"],

    "Ваш подарок −26%": ["Uw cadeau −26%", "Your −26% gift"],
    "Нажмите, чтобы открыть": ["Klik om te openen", "Tap to open"],
    "Скидка −26% активна": ["−26% korting actief", "−26% discount active"],
    "Выберите рекламный формат": ["Kies een advertentieformaat", "Choose an advertising format"],
    "Получить сезонную скидку 26 процентов": ["Seizoenskorting van 26 procent ontvangen", "Get the 26 percent seasonal discount"],
    "Скидка 26 процентов активна": ["26 procent korting actief", "26 percent discount active"],
    "Получить скидку 26 процентов": ["26 procent korting ontvangen", "Get 26 percent discount"],
    "Осень + праздничный сезон": ["Najaar + feestseizoen", "Autumn + holiday season"],
    "Заберите −26% на рекламу.": ["Activeer −26% op advertenties.", "Get −26% off advertising."],
    "−26% до конца года.": ["−26% tot het einde van het jaar.", "−26% through the end of the year."],
    "Подпишитесь на обновления для рекламодателей Podslushano.nl. Мы будем писать не чаще одного раза в месяц — о новых форматах, сезонных возможностях и важных изменениях. Скидка действует на рекламные форматы до 31 декабря 2026 года.": ["Meld u aan voor updates voor adverteerders van Podslushano.nl. We mailen maximaal één keer per maand over nieuwe formaten, seizoenskansen en belangrijke wijzigingen. De korting geldt op advertentieformaten tot en met 31 december 2026.", "Subscribe to Podslushano.nl advertiser updates. We will email no more than once a month about new formats, seasonal opportunities and important changes. The discount applies to advertising formats through December 31, 2026."],
    "Оставьте e-mail — активируем −26% на все рекламные форматы, включая Contact Guide.": ["Laat uw e-mailadres achter — we activeren −26% op alle advertentieformaten, inclusief Contact Guide.", "Leave your email — we will activate −26% on all advertising formats, including Contact Guide."],
    "Ваш e-mail": ["Uw e-mailadres", "Your email"],
    "Я согласен(на) получать рекламные обновления Podslushano.nl не чаще одного письма в месяц. Согласие можно отозвать.": ["Ik ga akkoord met het ontvangen van advertentie-updates van Podslushano.nl, maximaal één e-mail per maand. Ik kan mijn toestemming op elk moment intrekken.", "I agree to receive Podslushano.nl advertising updates no more than once a month. I can withdraw my consent at any time."],
    "Я согласен(на) получать рекламные обновления Podslushano.nl. Обычно 1 письмо в месяц, максимум 2 при отдельном важном поводе. Отписаться можно в любой момент.": ["Ik ga akkoord met advertentie-updates van Podslushano.nl. Meestal 1 e-mail per maand, maximaal 2 bij een afzonderlijke belangrijke aanleiding. Afmelden kan op elk moment.", "I agree to receive Podslushano.nl advertising updates. Usually 1 email per month, maximum 2 when there is a separate important update. You can unsubscribe at any time."],
    "Политика конфиденциальности": ["Privacybeleid", "Privacy policy"],
    "Получить скидку −26%": ["−26% korting activeren", "Activate −26% discount"],
    "Активировать −26%": ["−26% activeren", "Activate −26%"],
    "✓ Скидка активирована. Новые цены уже показаны на странице — выберите подходящий формат.": ["✓ Korting geactiveerd. De nieuwe prijzen staan al op de pagina — kies het passende formaat.", "✓ Discount activated. The new prices are already shown on the page — choose the right format."],
    "✓ Готово. Скидка активна — подтверждение отправили на e-mail.": ["✓ Gereed. De korting is actief — de bevestiging is per e-mail verzonden.", "✓ Done. Your discount is active — confirmation has been sent by email."],
    "✓ Готово. Скидка активна. Подписка сохранена — выберите подходящий формат.": ["✓ Gereed. De korting is actief. Uw inschrijving is opgeslagen — kies het passende formaat.", "✓ Done. Your discount is active. Your subscription is saved — choose the right format."],
    "Подтвердите подписку на обновления.": ["Bevestig uw inschrijving voor updates.", "Please confirm your subscription to updates."],
    "Активируем…": ["Activeren…", "Activating…"],
    "Не удалось активировать скидку.": ["De korting kon niet worden geactiveerd.", "Could not activate the discount."],
    "У вас подарок": ["U heeft een cadeau", "You have a gift"],
    "Открыть подарок и получить скидку 26 процентов": ["Cadeau openen en 26 procent korting ontvangen", "Open gift and get 26 percent discount"],
    "Закрыть": ["Sluiten", "Close"],

    "Оформление рекламы": ["Advertentie boeken", "Book advertising"],
    "Один выбранный день": ["Eén gekozen dag", "One selected day"],
    "1 публикация · закрепление 7 дней": ["1 publicatie · 7 dagen vastgezet", "1 publication · pinned for 7 days"],
    "Анонс + Zoom Q&A": ["Aankondiging + Zoom Q&A", "Announcement + Zoom Q&A"],
    "4 выхода за 60 дней": ["4 plaatsingen in 60 dagen", "4 placements over 60 days"],
    "Дата старта кампании": ["Startdatum campagne", "Campaign start date"],
    "Выберите дату": ["Kies een datum", "Choose a date"],
    "Выберите даты": ["Kies data", "Choose dates"],
    "Выберите дату старта": ["Kies de startdatum", "Choose the start date"],
    "Выберите дату эфира": ["Kies de sessiedatum", "Choose the session date"],
    "Нужно выбрать 4 свободные даты. Между соседними выходами — минимум 14 дней.": ["Kies 4 beschikbare data. Tussen opeenvolgende plaatsingen moeten minimaal 14 dagen zitten.", "Choose 4 available dates. Consecutive placements must be at least 14 days apart."],
    "Выберите свободную дату старта минимум за 7 дней. Остальные выходы согласуем после брифа.": ["Kies een beschikbare startdatum minimaal 7 dagen vooruit. De overige plaatsingen stemmen we na de briefing af.", "Choose an available start date at least 7 days in advance. We will agree the remaining placements after the brief."],
    "Выберите свободную дату эфира минимум за 7 дней — нужно время на анонс и набор вопросов.": ["Kies een beschikbare sessiedatum minimaal 7 dagen vooruit — we hebben tijd nodig voor de aankondiging en het verzamelen van vragen.", "Choose an available session date at least 7 days in advance — we need time for the announcement and to collect questions."],
    "Выберите один свободный день минимум за 2 дня. После оплаты публикация будет закреплена на 7 дней.": ["Kies een beschikbare dag minimaal 2 dagen vooruit. Na betaling wordt de publicatie 7 dagen vastgezet.", "Choose one available day at least 2 days in advance. After payment, the publication will be pinned for 7 days."],
    "Выберите один свободный день минимум за 2 дня.": ["Kies een beschikbare dag minimaal 2 dagen vooruit.", "Choose one available day at least 2 days in advance."],
    "свободно": ["beschikbaar", "available"],
    "занято / недоступно": ["bezet / niet beschikbaar", "booked / unavailable"],
    "выбрано": ["geselecteerd", "selected"],
    "Выбрано": ["Geselecteerd", "Selected"],
    "Пока ничего": ["Nog niets", "Nothing yet"],
    "Продолжить →": ["Doorgaan →", "Continue →"],
    "Между рекламными выходами должно быть минимум 14 дней.": ["Tussen advertentieplaatsingen moeten minimaal 14 dagen zitten.", "Advertising placements must be at least 14 days apart."],
    "Уже выбраны 4 даты. Снимите одну, чтобы заменить.": ["Er zijn al 4 data gekozen. Deselecteer er één om deze te vervangen.", "You have already selected 4 dates. Deselect one to replace it."],
    "Выберите 4 даты рекламных выходов.": ["Kies 4 data voor de advertentieplaatsingen.", "Choose 4 advertising placement dates."],
    "Выберите дату.": ["Kies een datum.", "Choose a date."],
    "Пн": ["Ma", "Mon"], "Вт": ["Di", "Tue"], "Ср": ["Wo", "Wed"], "Чт": ["Do", "Thu"], "Пт": ["Vr", "Fri"], "Сб": ["Za", "Sat"], "Вс": ["Zo", "Sun"],

    "Карточка Contact Guide Premium": ["Contact Guide Premium-profiel", "Contact Guide Premium listing"],
    "Этот шаг входит только в «Под ключ». После оплаты карточка создаётся на 2 месяца и сначала приходит администратору на проверку.": ["Deze stap hoort alleen bij ‘Volledig verzorgd’. Na betaling wordt het profiel voor 2 maanden aangemaakt en eerst ter controle aan de beheerder gestuurd.", "This step is included only in the Full-service campaign. After payment, the listing is created for 2 months and first sent to the administrator for review."],
    "Premium уже включён в стоимость.": ["Premium is al inbegrepen in de prijs.", "Premium is already included in the price."],
    "Фото/логотип, бейдж 🌟 и приоритет в выдаче входят в формат «Под ключ».": ["Foto/logo, badge 🌟 en voorrang in de zoekresultaten zijn inbegrepen bij ‘Volledig verzorgd’.", "Photo/logo, badge 🌟 and priority in search results are included in the Full-service campaign."],
    "Имя специалиста / название компании": ["Naam professional / bedrijfsnaam", "Professional name / company name"],
    "Например: Kova Executive": ["Bijvoorbeeld: Kova Executive", "For example: Kova Executive"],
    "Категория": ["Categorie", "Category"],
    "Выберите категорию": ["Kies een categorie", "Choose a category"],
    "Работаю онлайн / по всей стране": ["Ik werk online / landelijk", "I work online / nationwide"],
    "Если включено, город указывать не нужно.": ["Als dit is ingeschakeld, hoeft u geen plaats op te geven.", "If enabled, you do not need to enter a city."],
    "Город": ["Plaats", "City"],
    "Короткое описание": ["Korte beschrijving", "Short description"],
    "Что вы делаете, кому помогаете и с какими запросами к вам можно обратиться": ["Wat doet u, wie helpt u en met welke vragen kunnen mensen bij u terecht?", "What do you do, who do you help and what can people contact you about?"],
    "Публичный контакт": ["Openbare contactgegevens", "Public contact"],
    "Instagram, Telegram, сайт, e-mail или телефон": ["Instagram, Telegram, website, e-mail of telefoon", "Instagram, Telegram, website, email or phone"],
    "На следующем поле нужно загрузить фото или логотип для Premium-карточки.": ["In de volgende stap moet een foto of logo voor het Premium-profiel worden geüpload.", "In the next field, upload a photo or logo for the Premium listing."],
    "К реквизитам →": ["Naar factuurgegevens →", "Continue to billing details →"],
    "Укажите имя специалиста или название компании.": ["Vul de naam van de professional of het bedrijf in.", "Enter the professional or company name."],
    "Укажите город или выберите работу онлайн.": ["Vul een plaats in of kies online werken.", "Enter a city or select online work."],
    "Добавьте короткое понятное описание — минимум 20 символов.": ["Voeg een korte, duidelijke beschrijving toe — minimaal 20 tekens.", "Add a short, clear description — at least 20 characters."],
    "Укажите рабочий публичный контакт.": ["Vul geldige openbare contactgegevens in.", "Enter a valid public contact."],

    "Данные для factuur": ["Factuurgegevens", "Invoice details"],
    "Эти данные используются только для оплаты и счёта.": ["Deze gegevens worden alleen gebruikt voor betaling en facturering.", "These details are used only for payment and invoicing."],
    "Физлицо": ["Particulier", "Individual"],
    "Компания": ["Bedrijf", "Company"],
    "Имя и фамилия": ["Voor- en achternaam", "First and last name"],
    "Название компании": ["Bedrijfsnaam", "Company name"],
    "BTW-номер (необязательно)": ["Btw-nummer (optioneel)", "VAT number (optional)"],
    "KVK-номер (необязательно)": ["KvK-nummer (optioneel)", "Chamber of Commerce number (optional)"],
    "Адрес": ["Adres", "Address"],
    "Почтовый индекс": ["Postcode", "Postal code"],
    "E-mail для счёта": ["E-mailadres voor de factuur", "Invoice email"],
    "Телефон (необязательно)": ["Telefoon (optioneel)", "Phone (optional)"],
    "Данные factuur вводите латиницей, как в документах.": ["Vul de factuurgegevens met Latijnse letters in, precies zoals in uw documenten.", "Enter invoice details using Latin characters, exactly as in your documents."],
    "Проверить заказ →": ["Bestelling controleren →", "Review order →"],
    "Укажите название компании.": ["Vul de bedrijfsnaam in.", "Enter the company name."],
    "Укажите имя и фамилию.": ["Vul uw voor- en achternaam in.", "Enter your first and last name."],
    "Укажите адрес для factuur.": ["Vul het factuuradres in.", "Enter the invoice address."],
    "Укажите почтовый индекс.": ["Vul de postcode in.", "Enter the postal code."],
    "Укажите корректный e-mail.": ["Vul een geldig e-mailadres in.", "Enter a valid email address."],

    "Проверьте заказ": ["Controleer uw bestelling", "Review your order"],
    "После оплаты рекламная дата фиксируется за вами.": ["Na betaling wordt de advertentiedatum voor u vastgelegd.", "After payment, the advertising date is secured for you."],
    "Я ознакомился(ась) и принимаю условия сотрудничества. Оплата означает согласие с ними.": ["Ik heb de samenwerkingsvoorwaarden gelezen en ga ermee akkoord. Betaling betekent dat ik deze voorwaarden accepteer.", "I have read and accept the terms of cooperation. Payment means I agree to these terms."],
    "Перейти к Mollie →": ["Naar Mollie →", "Continue to Mollie →"],
    "Подтвердите согласие с условиями сотрудничества.": ["Bevestig dat u akkoord gaat met de samenwerkingsvoorwaarden.", "Please confirm that you accept the terms of cooperation."],
    "Формат": ["Formaat", "Format"],
    "Стоимость": ["Prijs", "Price"],
    "Старт": ["Start", "Start"],
    "Дата эфира": ["Sessiedatum", "Session date"],
    "Дата": ["Datum", "Date"],
    "Даты": ["Data", "Dates"],
    "Карточка": ["Profiel", "Listing"],
    "Фото / логотип": ["Foto / logo", "Photo / logo"],
    "добавлено": ["toegevoegd", "added"],
    "Плательщик": ["Betaler", "Payer"],
    "2 месяца": ["2 maanden", "2 months"],

    "парикмахер": ["kapper", "hairdresser"],
    "мастер маникюра": ["nagelstylist", "nail technician"],
    "брови и ресницы": ["wenkbrauwen en wimpers", "brows and lashes"],
    "перманентный макияж": ["permanente make-up", "permanent makeup"],
    "визажист": ["make-up artist", "makeup artist"],
    "косметолог": ["schoonheidsspecialist", "beautician"],
    "эпиляция": ["ontharing", "hair removal"],
    "массаж": ["massage", "massage"],
    "тату и пирсинг": ["tattoo en piercing", "tattoo and piercing"],
    "стилист": ["stylist", "stylist"],
    "стоматолог": ["tandarts", "dentist"],
    "врач": ["arts", "doctor"],
    "психолог": ["psycholoog", "psychologist"],
    "коуч": ["coach", "coach"],
    "нутрициолог": ["voedingsdeskundige", "nutrition specialist"],
    "фитнес": ["fitness", "fitness"],
    "юрист": ["jurist", "lawyer"],
    "бухгалтер": ["boekhouder", "accountant"],
    "переводчик": ["vertaler", "translator"],
    "риелтор": ["makelaar", "real estate agent"],
    "it и веб": ["IT en web", "IT and web"],
    "маркетинг": ["marketing", "marketing"],
    "дизайнер": ["designer", "designer"],
    "бизнес-консалтинг": ["bedrijfsadvies", "business consulting"],
    "карьерный консультант": ["loopbaanadviseur", "career consultant"],
    "фотограф": ["fotograaf", "photographer"],
    "видеограф": ["videograaf", "videographer"],
    "ведущий": ["presentator", "host"],
    "музыкант и диджей": ["muzikant en dj", "musician and DJ"],
    "организация мероприятий": ["evenementenorganisatie", "event organisation"],
    "декор": ["decoratie", "decor"],
    "аниматор": ["entertainer", "entertainer"],
    "кондитер": ["banketbakker", "pastry chef"],
    "кейтеринг": ["catering", "catering"],
    "продукты и магазины": ["producten en winkels", "products and shops"],
    "ремонт": ["renovatie", "renovation"],
    "мастер на час": ["klusjesman", "handyman"],
    "клининг": ["schoonmaak", "cleaning"],
    "переезды": ["verhuizingen", "moving services"],
    "автосервис": ["autogarage", "car service"],
    "автошкола": ["rijschool", "driving school"],
    "репетитор": ["bijlesdocent", "tutor"],
    "языковые курсы": ["taalcursussen", "language courses"],
    "музыкальные занятия": ["muzieklessen", "music lessons"],
    "няня": ["oppas", "nanny"],
    "детские занятия": ["kinderactiviteiten", "children’s activities"],
    "гид": ["gids", "guide"],
    "творчество": ["creativiteit", "creative services"]
  };

  const monthNom = {
    "январь": ["januari", "January"], "февраль": ["februari", "February"], "март": ["maart", "March"],
    "апрель": ["april", "April"], "май": ["mei", "May"], "июнь": ["juni", "June"],
    "июль": ["juli", "July"], "август": ["augustus", "August"], "сентябрь": ["september", "September"],
    "октябрь": ["oktober", "October"], "ноябрь": ["november", "November"], "декабрь": ["december", "December"]
  };
  const monthGen = {
    "января": ["januari", "January"], "февраля": ["februari", "February"], "марта": ["maart", "March"],
    "апреля": ["april", "April"], "мая": ["mei", "May"], "июня": ["juni", "June"],
    "июля": ["juli", "July"], "августа": ["augustus", "August"], "сентября": ["september", "September"],
    "октября": ["oktober", "October"], "ноября": ["november", "November"], "декабря": ["december", "December"]
  };

  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();
  let translating = false;

  function lang() {
    const current = (document.documentElement.lang || "ru").toLowerCase();
    return SUPPORTED.includes(current) ? current : "ru";
  }

  function norm(value) { return String(value || "").replace(/\s+/g, " ").trim(); }

  function translateDate(source, active) {
    const clean = norm(source);
    let match = clean.match(/^(январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+(\d{4})\s*г\.?$/i);
    if (match) {
      const m = monthNom[match[1].toLowerCase()];
      return active === "nl" ? `${m[0]} ${match[2]}` : `${m[1]} ${match[2]}`;
    }
    match = clean.match(/^(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})\s*г\.?$/i);
    if (match) {
      const m = monthGen[match[2].toLowerCase()];
      return active === "nl" ? `${match[1]} ${m[0]} ${match[3]}` : `${m[1]} ${match[1]}, ${match[3]}`;
    }
    if (clean.includes(" · ")) {
      const parts = clean.split(" · ");
      const converted = parts.map(part => translateDate(part, active));
      if (converted.some((part, index) => part !== parts[index])) return converted.join(" · ");
    }
    return null;
  }

  function lookup(source, active) {
    if (active === "ru") return source;
    const key = norm(source);
    const exact = translations[key];
    if (exact) return exact[active === "nl" ? 0 : 1];

    const date = translateDate(key, active);
    if (date) return date;

    let match = key.match(/^Выбрать\s+(€[\d.,]+)$/);
    if (match) return active === "nl" ? `Kies ${match[1]}` : `Choose ${match[1]}`;
    match = key.match(/^Сезонная цена после подписки:\s*(€[\d.,]+)$/);
    if (match) return active === "nl" ? `🎁 Seizoensprijs na inschrijving: ${match[1]}` : `🎁 Seasonal price after subscribing: ${match[1]}`;
    return source;
  }

  function translateTextNode(node) {
    if (!originalText.has(node)) originalText.set(node, node.nodeValue || "");
    const source = originalText.get(node);
    if (!source || !source.trim()) return;

    const parent = node.parentElement;
    if (parent && parent.tagName === "OPTION" && !parent.hasAttribute("value")) {
      parent.setAttribute("value", norm(source));
    }

    const leading = source.match(/^\s*/)[0];
    const trailing = source.match(/\s*$/)[0];
    const next = leading + lookup(source, lang()) + trailing;
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  function translateElement(element) {
    if (!(element instanceof Element) || element.closest(".pnl-language-switcher")) return;
    let attrs = originalAttrs.get(element);
    if (!attrs) {
      attrs = {};
      ["placeholder", "aria-label", "title"].forEach(name => {
        if (element.hasAttribute(name)) attrs[name] = element.getAttribute(name);
      });
      originalAttrs.set(element, attrs);
    }
    Object.entries(attrs).forEach(([name, source]) => {
      element.setAttribute(name, lookup(source, lang()));
    });
  }

  function updateLinks() {
    const active = lang();
    document.querySelectorAll('a[href^="/privacy?lang="]').forEach(link => {
      link.setAttribute("href", `/privacy?lang=${active}`);
    });
  }

  function walk(root = document.body) {
    if (!root) return;
    translating = true;
    if (root.nodeType === Node.TEXT_NODE) translateTextNode(root);
    if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      else translateElement(node);
    }
    updateLinks();
    translating = false;
  }

  function start() {
    walk();

    new MutationObserver(records => {
      if (translating) return;
      let languageChanged = false;
      records.forEach(record => {
        if (record.type === "attributes" && record.target === document.documentElement && record.attributeName === "lang") {
          languageChanged = true;
        }
        record.addedNodes.forEach(node => walk(node));
      });
      if (languageChanged) walk();
    }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["lang"] });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();