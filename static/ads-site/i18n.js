/* Podslushano.nl ads page localization: RU / NL / EN. */
(() => {
  "use strict";

  const STORAGE_KEY = "pnl-ads-language";
  const SWITCHER_ID = "pnl-language-switcher";
  const STYLE_ID = "pnl-language-switcher-style";
  const SUPPORTED = ["ru", "nl", "en"];
  const translations = {
    "Реклама — Podslushano.nl": ["Adverteren — Podslushano.nl", "Advertising — Podslushano.nl"],
    "Рекламные форматы Podslushano.nl для русскоязычной аудитории Нидерландов.": ["Advertentiemogelijkheden van Podslushano.nl voor de Russischtalige doelgroep in Nederland.", "Podslushano.nl advertising options for the Russian-speaking audience in the Netherlands."],
    "Знакомство": ["Introductie", "Introduction"], "Формат": ["Formaat", "Format"], "Дата": ["Datum", "Date"],
    "Данные": ["Gegevens", "Details"], "Оплата": ["Betaling", "Payment"], "Фактура": ["Factuur", "Invoice"],
    "Этапы оформления": ["Stappen van de bestelling", "Order steps"],
    "Podslushano.nl · Реклама": ["Podslushano.nl · Adverteren", "Podslushano.nl · Advertising"],
    "Ваш проект — перед русскоязычной аудиторией Нидерландов": ["Uw project onder de aandacht van de Russischtalige doelgroep in Nederland", "Put your project in front of the Russian-speaking audience in the Netherlands"],
    "Выберите рекламный формат, свободную дату и оформите всё онлайн — прозрачно и без долгой переписки.": ["Kies een advertentieformaat en een beschikbare datum en regel alles online — transparant en zonder lange correspondentie.", "Choose an advertising format and an available date, then arrange everything online — transparently and without lengthy correspondence."],
    "Только 7 дней": ["Slechts 7 dagen", "Only 7 days"], "«Продвижение» дешевле на €30": ["€30 korting op ‘Promotie’", "Save €30 on ‘Promotion’"],
    "Посмотреть форматы": ["Bekijk de formaten", "View formats"], "BTW 21% включён": ["21% btw inbegrepen", "21% VAT included"],
    "Оплата через Mollie": ["Betaling via Mollie", "Payment via Mollie"], "Фактура на e-mail": ["Factuur per e-mail", "Invoice by email"],
    "просмотров / месяц": ["weergaven / maand", "views / month"], "взаимодействий": ["interacties", "interactions"],
    "женщины / мужчины": ["vrouwen / mannen", "women / men"], "русскоязычная аудитория": ["Russischtalige doelgroep", "Russian-speaking audience"],
    "Данные аудитории на июнь 2026": ["Doelgroepgegevens van juni 2026", "Audience data as of June 2026"],
    "Перед оформлением": ["Voorafgaand aan uw bestelling", "Before you order"], "Частые вопросы": ["Veelgestelde vragen", "Frequently asked questions"],
    "Важная информация о датах, материалах, оплате и фактуре.": ["Belangrijke informatie over data, materialen, betaling en facturering.", "Important information about dates, materials, payment and invoicing."],
    "Как происходит оплата?": ["Hoe werkt de betaling?", "How does payment work?"],
    "Через Mollie (iDEAL, карты). Оплата — 100% предоплата; дата выхода фиксируется только после оплаты.": ["Via Mollie (iDEAL of betaalkaart). U betaalt 100% vooraf; de publicatiedatum wordt pas na betaling vastgelegd.", "Via Mollie (iDEAL or card). Payment is 100% upfront; the publication date is secured only after payment."],
    "Как выбрать дату?": ["Hoe kies ik een datum?", "How do I choose a date?"],
    "В календаре доступны только свободные даты. В «Продвижении» нужно выбрать 4 даты с интервалом минимум 14 дней.": ["De kalender toont alleen beschikbare data. Voor ‘Promotie’ kiest u vier data met minimaal 14 dagen ertussen.", "The calendar shows available dates only. For ‘Promotion’, choose four dates at least 14 days apart."],
    "Кто готовит материал?": ["Wie maakt het materiaal?", "Who prepares the material?"],
    "Зависит от формата: мы помогаем с подачей и адаптируем текст под аудиторию. Материалы предоставляются не позднее чем за 48 часов до публикации.": ["Dat hangt af van het formaat: wij helpen met de presentatie en passen de tekst aan de doelgroep aan. Lever het materiaal uiterlijk 48 uur voor publicatie aan.", "It depends on the format: we help with presentation and adapt the copy to the audience. Materials must be supplied no later than 48 hours before publication."],
    "Можно ли вернуть деньги?": ["Kan ik mijn geld terugkrijgen?", "Can I get a refund?"],
    "За уже опубликованную (полностью или частично) рекламу возврата нет. Для физлиц действует 14-дневное право на отзыв до публикации — возвращаем за неоказанную часть.": ["Voor reeds geheel of gedeeltelijk gepubliceerde advertenties geldt geen terugbetaling. Consumenten hebben vóór publicatie 14 dagen herroepingsrecht; het niet-geleverde deel wordt terugbetaald.", "There are no refunds for advertising already published in full or in part. Consumers have a 14-day right of withdrawal before publication; we refund the undelivered portion."],
    "Даёте ли вы статистику охватов?": ["Delen jullie bereikstatistieken?", "Do you provide reach statistics?"],
    "Да, по запросу пришлём актуальную статистику аудитории и охватов перед размещением.": ["Ja, op verzoek sturen we vóór plaatsing actuele doelgroep- en bereikstatistieken.", "Yes. On request, we will send current audience and reach statistics before placement."],
    "На каком языке вводить данные для счёта?": ["In welke taal moet ik de factuurgegevens invullen?", "Which language should I use for invoice details?"],
    "Латиницей, как в документах (например, Alex Mair) — иначе фактура будет некорректной.": ["Gebruik Latijnse letters, precies zoals in uw documenten (bijvoorbeeld Alex Mair), anders is de factuur onjuist.", "Use Latin characters exactly as in your documents (for example, Alex Mair), otherwise the invoice will be incorrect."],
    "Эксперт месяца": ["Expert van de maand", "Expert of the Month"], "⭐ Рекомендуем": ["⭐ Aanbevolen", "⭐ Recommended"],
    "Постоянное присутствие и поток клиентов из поиска в боте. Абонемент.": ["Blijvende zichtbaarheid en klanten via de zoekfunctie van de bot. Abonnement.", "Ongoing visibility and customer leads from search in the bot. Subscription."],
    "топ выдачи в боте с пометкой «⭐ Рекомендуем» — когда человек ищет специалиста в вашей категории, он видит вас первым весь срок": ["bovenaan de zoekresultaten in de bot met het label ‘⭐ Aanbevolen’ — u staat gedurende de hele looptijd als eerste bij zoekopdrachten in uw categorie", "top placement in bot search with a ‘⭐ Recommended’ label — you appear first whenever someone searches your category throughout the term"],
    "нативный экспертный пост (проблема → решение) в Instagram + дубль в Telegram": ["native expertpost (probleem → oplossing) op Instagram + herhaling op Telegram", "native expert post (problem → solution) on Instagram + repost on Telegram"],
    "сторис-поддержка": ["ondersteuning via Stories", "Stories support"], "«вопрос эксперту» — отвечаете на реальный вопрос аудитории": ["‘vraag aan de expert’ — beantwoord een echte vraag van de doelgroep", "‘ask the expert’ — answer a real audience question"],
    "статус «Эксперт месяца»": ["status ‘Expert van de maand’", "‘Expert of the Month’ status"],
    "юристам, бухгалтерам, риелторам, психологам, мастерам, локальным сервисам и экспертам": ["advocaten, accountants, makelaars, psychologen, vakmensen, lokale diensten en experts", "lawyers, accountants, estate agents, psychologists, tradespeople, local services and experts"],
    "1 месяц": ["1 maand", "1 month"], "3 месяца — выгоднее": ["3 maanden — voordeliger", "3 months — better value"],
    "Продвижение": ["Promotie", "Promotion"], "−€30 · 7 дней": ["−€30 · 7 dagen", "−€30 · 7 days"],
    "Кампания на 2 месяца: четыре нативных касания в Instagram и Telegram.": ["Campagne van twee maanden: vier native contactmomenten op Instagram en Telegram.", "A two-month campaign with four native touchpoints on Instagram and Telegram."],
    "4 публикации в Instagram (нативная подача: проблема → решение)": ["4 Instagram-publicaties (native aanpak: probleem → oplossing)", "4 Instagram publications (native approach: problem → solution)"],
    "вы выбираете 4 даты выхода (минимум 14 дней между ними)": ["u kiest 4 publicatiedata (minimaal 14 dagen ertussen)", "you choose 4 publication dates (at least 14 days apart)"],
    "2 сторис к каждой публикации": ["2 Stories bij elke publicatie", "2 Stories with each publication"],
    "Telegram-пост и присутствие в канале 2 месяца": ["Telegram-post en 2 maanden zichtbaarheid in het kanaal", "Telegram post and 2 months of channel visibility"],
    "адаптация подачи под аудиторию": ["presentatie afgestemd op de doelgroep", "presentation adapted to the audience"],
    "услугам, экспертам, локальным бизнесам и проектам": ["diensten, experts, lokale bedrijven en projecten", "services, experts, local businesses and projects"],
    "4 выхода / 2 месяца": ["4 publicaties / 2 maanden", "4 publications / 2 months"],
    "Telegram-пост": ["Telegram-post", "Telegram post"], "Рекламный пост в Telegram-канале с закреплением на 7 дней.": ["Advertentiepost in het Telegram-kanaal, 7 dagen vastgezet.", "Advertising post in the Telegram channel, pinned for 7 days."],
    "1 рекламный пост в Telegram-канале": ["1 advertentiepost in het Telegram-kanaal", "1 advertising post in the Telegram channel"],
    "Закрепление поста на 7 дней": ["Post 7 dagen vastgezet", "Post pinned for 7 days"], "Адаптация текста под аудиторию": ["Tekst aangepast aan de doelgroep", "Copy adapted to the audience"],
    "Ссылка, контакт или CTA": ["Link, contactgegevens of CTA", "Link, contact details or CTA"],
    "услугам, мероприятиям, срочным анонсам, акциям и локальным предложениям": ["diensten, evenementen, urgente aankondigingen, acties en lokale aanbiedingen", "services, events, urgent announcements, promotions and local offers"],
    "1 пост + закреп 7 дней": ["1 post + 7 dagen vastgezet", "1 post + 7-day pin"], "Повторная публикация через 14 дней (тот же пост)": ["Herplaatsing na 14 dagen (dezelfde post)", "Repost after 14 days (same post)"],
    "Афиша": ["Agenda", "Events"], "Анонс события в Instagram (пост-анонс).": ["Aankondiging van een evenement op Instagram.", "Event announcement on Instagram."],
    "пост-анонс события в Instagram": ["aankondigingspost voor een evenement op Instagram", "event announcement post on Instagram"],
    "краткое описание, дата, город и стоимость": ["korte beschrijving, datum, plaats en prijs", "short description, date, city and price"],
    "мероприятиям, концертам, экскурсиям, мастер-классам, лекциям, вечеринкам": ["evenementen, concerten, rondleidingen, workshops, lezingen en feesten", "events, concerts, tours, workshops, lectures and parties"],
    "Афиша+": ["Agenda+", "Events+"], "Расширенный": ["Uitgebreid", "Extended"],
    "Instagram и дополнительное размещение в «Афише месяца» в Telegram-боте.": ["Instagram plus extra plaatsing in de ‘Agenda van de maand’ in de Telegram-bot.", "Instagram plus an additional listing in the ‘Events of the Month’ section of the Telegram bot."],
    "всё из «Афиши»": ["alles uit ‘Agenda’", "everything in ‘Events’"], "размещение в подборке «Афиша месяца» в Telegram-боте": ["plaatsing in ‘Agenda van de maand’ in de Telegram-bot", "listing in ‘Events of the Month’ in the Telegram bot"],
    "дополнительная сторис-поддержка": ["extra ondersteuning via Stories", "additional Stories support"], "ссылка на билеты или регистрацию": ["link naar tickets of registratie", "ticket or registration link"],
    "событиям, где важны продажи билетов и регистрация": ["evenementen waarvoor ticketverkoop en registratie belangrijk zijn", "events where ticket sales and registrations matter"],
    "Instagram + Telegram-бот": ["Instagram + Telegram-bot", "Instagram + Telegram bot"],
    "ЭКСПЕРТ": ["EXPERT", "EXPERT"], "Рекомендация месяца": ["Aanbeveling van de maand", "Recommendation of the month"],
    "4 ВЫХОДА": ["4 PUBLICATIES", "4 PUBLICATIONS"], "Пост · закреп 7 дней": ["Post · 7 dagen vastgezet", "Post · pinned for 7 days"],
    "АФИША": ["AGENDA", "EVENTS"], "Событие в Нидерландах": ["Evenement in Nederland", "Event in the Netherlands"],
    "АФИША+": ["AGENDA+", "EVENTS+"], "Instagram + бот": ["Instagram + bot", "Instagram + bot"],
    "Реклама, которую видят свои": ["Advertenties die uw doelgroep ziet", "Advertising your community sees"], "своих рядом": ["mensen in de buurt", "people nearby"],
    "7 дней": ["7 dagen", "7 days"], "4 поста": ["4 posts", "4 posts"], "Билеты →": ["Tickets →", "Tickets →"], "свои увидят": ["uw doelgroep ziet het", "your audience will see it"],
    "Скидка €30 на формат «Продвижение»": ["€30 korting op het formaat ‘Promotie’", "€30 discount on the ‘Promotion’ format"],
    "Шаг 2 из 6": ["Stap 2 van 6", "Step 2 of 6"], "Выберите формат": ["Kies een formaat", "Choose a format"],
    "Откройте карточку, чтобы посмотреть состав размещения и выбрать подходящий вариант.": ["Open een kaart om de inhoud te bekijken en de passende optie te kiezen.", "Open a card to see what is included and choose the right option."],
    "от": ["vanaf", "from"], "Подробнее и выбрать →": ["Meer informatie en kiezen →", "View details and choose →"], "← Назад": ["← Terug", "← Back"],
    "Закрыть": ["Sluiten", "Close"], "Рекламный формат": ["Advertentieformaat", "Advertising format"], "Скидка действует 7 дней": ["Korting geldig gedurende 7 dagen", "Discount valid for 7 days"],
    "Что входит": ["Wat is inbegrepen", "What's included"], "Кому подходит": ["Voor wie is dit geschikt", "Who it's for"], "Выбрать этот формат": ["Kies dit formaat", "Choose this format"],
    "Шаг 3 из 6": ["Stap 3 van 6", "Step 3 of 6"], "Выберите вариант и дату": ["Kies een optie en datum", "Choose an option and date"],
    "Показываем только доступные даты. Занятые дни выбрать нельзя.": ["We tonen alleen beschikbare data. Bezette dagen kunnen niet worden gekozen.", "We only show available dates. Booked dates cannot be selected."],
    "Проверяем свободные даты…": ["Beschikbare data controleren…", "Checking available dates…"], "Изменить": ["Wijzigen", "Change"],
    "Длительность / вариант": ["Looptijd / optie", "Duration / option"], "Выберите свободную дату": ["Kies een beschikbare datum", "Choose an available date"],
    "Интервал между публикациями — минимум 14 дней": ["Minimaal 14 dagen tussen publicaties", "At least 14 days between publications"],
    "Между публикациями должно быть не менее 14 дней.": ["Tussen publicaties moeten minimaal 14 dagen zitten.", "Publications must be at least 14 days apart."],
    "свободно": ["beschikbaar", "available"], "недоступно": ["niet beschikbaar", "unavailable"], "выбрано": ["geselecteerd", "selected"],
    "Дата пока не выбрана": ["Nog geen datum gekozen", "No date selected yet"], "← Форматы": ["← Formaten", "← Formats"],
    "Выберите свободную дату.": ["Kies een beschikbare datum.", "Choose an available date."], "Продолжить →": ["Doorgaan →", "Continue →"],
    "Пн": ["Ma", "Mon"], "Вт": ["Di", "Tue"], "Ср": ["Wo", "Wed"], "Чт": ["Do", "Thu"], "Пт": ["Vr", "Fri"], "Сб": ["Za", "Sat"], "Вс": ["Zo", "Sun"],
    "Шаг 4 из 6": ["Stap 4 van 6", "Step 4 of 6"], "Данные для фактуры": ["Factuurgegevens", "Invoice details"],
    "Фактура формируется только после успешной оплаты на следующем шаге.": ["De factuur wordt pas na een geslaagde betaling in de volgende stap aangemaakt.", "The invoice is created only after successful payment in the next step."],
    "Примите условия сотрудничества.": ["Accepteer de samenwerkingsvoorwaarden.", "Accept the terms of cooperation."], "Заполните обязательные поля.": ["Vul de verplichte velden in.", "Complete the required fields."],
    "Кто оплачивает": ["Wie betaalt", "Who is paying"], "Физлицо": ["Particulier", "Individual"], "Компания": ["Bedrijf", "Company"],
    "Все данные вводите латиницей, как в документах.": ["Vul alle gegevens met Latijnse letters in, zoals in uw documenten.", "Enter all details in Latin characters, exactly as in your documents."],
    "Название компании": ["Bedrijfsnaam", "Company name"], "Имя и фамилия": ["Voor- en achternaam", "First and last name"],
    "BTW-номер": ["Btw-nummer", "VAT number"], "необязательно": ["optioneel", "optional"], "KVK-номер": ["KvK-nummer", "Chamber of Commerce number"],
    "Телефон": ["Telefoon", "Phone"], "Адрес": ["Adres", "Address"], "Почтовый индекс": ["Postcode", "Postal code"],
    "E-mail для оплаченной фактуры": ["E-mailadres voor de betaalde factuur", "Email address for the paid invoice"],
    "Условия сотрудничества": ["Samenwerkingsvoorwaarden", "Terms of cooperation"], "Исполнитель: Podslushano.nl": ["Dienstverlener: Podslushano.nl", "Service provider: Podslushano.nl"],
    "Я ознакомился(ась) и принимаю условия сотрудничества. Оплата означает полное согласие с ними.": ["Ik heb de samenwerkingsvoorwaarden gelezen en ga ermee akkoord. Betaling betekent volledige aanvaarding van deze voorwaarden.", "I have read and accept the terms of cooperation. Payment constitutes full acceptance of these terms."],
    "← Дата": ["← Datum", "← Date"], "Проверить заказ →": ["Bestelling controleren →", "Review order →"],
    "Шаг 5 из 6": ["Stap 5 van 6", "Step 5 of 6"], "Проверьте и оплатите": ["Controleer en betaal", "Review and pay"],
    "После нажатия кнопки вы перейдёте на защищённую страницу Mollie. До оплаты дата ещё не считается забронированной.": ["Na het klikken gaat u naar de beveiligde betaalpagina van Mollie. De datum is pas na betaling gereserveerd.", "After clicking, you will be redirected to Mollie's secure payment page. The date is not reserved until payment is complete."],
    "Вариант": ["Optie", "Option"], "Даты": ["Data", "Dates"], "Плательщик": ["Betaler", "Payer"], "E-mail для фактуры": ["E-mailadres voor de factuur", "Invoice email"], "Итого": ["Totaal", "Total"],
    "После оплаты": ["Na betaling", "After payment"], "Дата закрепится за вами, а оплаченная фактура придёт на e-mail.": ["De datum wordt voor u vastgelegd en de betaalde factuur wordt per e-mail verzonden.", "The date will be secured for you and the paid invoice will be sent by email."],
    "← Изменить": ["← Wijzigen", "← Edit"], "Оплатить": ["Betaal", "Pay"], "через Mollie →": ["via Mollie →", "via Mollie →"], "100% предоплата · iDEAL и банковские карты · BTW 21% включён.": ["100% vooruitbetaling · iDEAL en betaalkaarten · 21% btw inbegrepen.", "100% upfront payment · iDEAL and bank cards · 21% VAT included."],
    "Шаг 6 из 6 · Готово": ["Stap 6 van 6 · Gereed", "Step 6 of 6 · Complete"], "Оплата подтверждена": ["Betaling bevestigd", "Payment confirmed"],
    "Дата закреплена за вами. Оплаченная фактура отправлена на указанный e-mail.": ["De datum is voor u vastgelegd. De betaalde factuur is naar het opgegeven e-mailadres verzonden.", "The date has been secured for you. The paid invoice has been sent to the email address provided."],
    "Важно": ["Belangrijk", "Important"], "Если письма нет во входящих, проверьте папку «Спам».": ["Controleer de map ‘Spam’ als de e-mail niet in uw inbox staat.", "If the email is not in your inbox, check your Spam folder."],
    "Вернуться в начало": ["Terug naar het begin", "Return to the start"], "Есть вопросы?": ["Vragen?", "Questions?"],
    "Заказ принят": ["Bestelling ontvangen", "Order received"], "Спасибо за оплату!": ["Bedankt voor uw betaling!", "Thank you for your payment!"],
    "После подтверждения платежа выбранная дата закрепляется за вами. Оплаченная фактура придёт на указанный e-mail.": ["Na bevestiging van de betaling wordt de gekozen datum voor u vastgelegd. De betaalde factuur wordt naar het opgegeven e-mailadres gestuurd.", "Once payment is confirmed, the selected date will be secured for you. The paid invoice will be sent to the email address provided."],
    "Номер платежа:": ["Betalingsnummer:", "Payment number:"], "Что дальше": ["Wat gebeurt er nu?", "What happens next"],
    "Мы свяжемся с вами по данным из заказа. Если письма нет во входящих, проверьте папку «Спам».": ["We nemen contact met u op via de gegevens in uw bestelling. Controleer de map ‘Spam’ als de e-mail niet in uw inbox staat.", "We will contact you using the details in your order. If the email is not in your inbox, check your Spam folder."],
    "Вернуться на рекламную страницу": ["Terug naar de advertentiepagina", "Return to the advertising page"],
    "Оплаченная фактура будет отправлена на e-mail, указанный при оформлении.": ["De betaalde factuur wordt naar het bij de bestelling opgegeven e-mailadres verzonden.", "The paid invoice will be sent to the email address provided during checkout."],
    "Оплата не завершена": ["Betaling niet voltooid", "Payment not completed"], "Платёж не прошёл": ["Betaling mislukt", "Payment failed"],
    "Деньги не списаны, дата не закреплена. Вернитесь и попробуйте ещё раз.": ["Er is niets afgeschreven en de datum is niet vastgelegd. Ga terug en probeer het opnieuw.", "No money was charged and the date was not secured. Go back and try again."],
    "Проверяем платёж": ["Betaling controleren", "Checking payment"], "Оплата обрабатывается": ["Betaling wordt verwerkt", "Payment is processing"],
    "Mollie ещё не подтвердил платёж. Обновите эту страницу через несколько секунд.": ["Mollie heeft de betaling nog niet bevestigd. Vernieuw deze pagina over enkele seconden.", "Mollie has not confirmed the payment yet. Refresh this page in a few seconds."],
    "Безопасная оплата": ["Veilige betaling", "Secure payment"], "Открываем Mollie": ["Mollie openen", "Opening Mollie"],
    "Платёжная страница откроется отдельно.": ["De betaalpagina wordt afzonderlijk geopend.", "The payment page will open separately."],
    "Открыть оплату Mollie": ["Mollie-betaling openen", "Open Mollie payment"], "Вернуться назад": ["Terug", "Go back"],
    "← Вернуться к рекламе": ["← Terug naar adverteren", "← Back to advertising"], "Поможем разобраться": ["We helpen u graag", "We're here to help"],
    "Посмотрите короткие ответы или напишите нам. Обычно отвечаем в течение рабочего дня.": ["Bekijk de korte antwoorden of neem contact met ons op. We reageren meestal binnen één werkdag.", "Read the short answers or contact us. We usually respond within one business day."],
    "Через защищённую страницу Mollie: iDEAL или банковской картой. Дата фиксируется только после успешной оплаты.": ["Via de beveiligde betaalpagina van Mollie met iDEAL of betaalkaart. De datum wordt pas na een geslaagde betaling vastgelegd.", "Via Mollie's secure payment page using iDEAL or a bank card. The date is secured only after successful payment."],
    "В календаре доступны только свободные даты. Для формата «Продвижение» выберите четыре даты с интервалом не менее 14 дней.": ["De kalender toont alleen beschikbare data. Kies voor ‘Promotie’ vier data met minimaal 14 dagen ertussen.", "The calendar shows available dates only. For ‘Promotion’, choose four dates at least 14 days apart."],
    "Кто готовит рекламный материал?": ["Wie maakt het advertentiemateriaal?", "Who prepares the advertising material?"],
    "Мы помогаем с подачей и адаптируем текст под аудиторию. Исходные материалы нужно предоставить не позднее чем за 48 часов до публикации.": ["Wij helpen met de presentatie en passen de tekst aan de doelgroep aan. Lever het bronmateriaal uiterlijk 48 uur voor publicatie aan.", "We help with presentation and adapt the copy to the audience. Source materials must be supplied no later than 48 hours before publication."],
    "Когда придёт фактура?": ["Wanneer ontvang ik de factuur?", "When will I receive the invoice?"],
    "Оплаченная фактура автоматически отправляется на e-mail, указанный при оформлении заказа.": ["De betaalde factuur wordt automatisch naar het bij de bestelling opgegeven e-mailadres verzonden.", "The paid invoice is automatically sent to the email address provided during checkout."],
    "Написать на e-mail →": ["E-mail ons →", "Email us →"], "Открыть Instagram": ["Instagram openen", "Open Instagram"]
  };

  const legal = [
    ["1. Общие положения", "1. Algemene bepalingen", "1. General provisions"],
    ["Каждое размещение является отдельным соглашением между сторонами. Предыдущие договорённости и условия не применяются автоматически к новым размещениям.", "Elke plaatsing vormt een afzonderlijke overeenkomst tussen de partijen. Eerdere afspraken en voorwaarden zijn niet automatisch van toepassing op nieuwe plaatsingen.", "Each placement constitutes a separate agreement between the parties. Previous arrangements and terms do not automatically apply to new placements."],
    ["2. Принятие условий", "2. Aanvaarding van de voorwaarden", "2. Acceptance of terms"],
    ["Оплата инвойса или платёжной ссылки означает полное согласие с данными условиями. Переписка (Instagram Direct, Telegram, Email) имеет юридическую силу и фиксирует договорённости сторон.", "Betaling van de factuur of betaallink betekent volledige aanvaarding van deze voorwaarden. Correspondentie via Instagram Direct, Telegram en e-mail is rechtsgeldig en legt de afspraken tussen partijen vast.", "Payment of the invoice or payment link constitutes full acceptance of these terms. Correspondence via Instagram Direct, Telegram and email is legally valid and records the parties' agreements."],
    ["3. Оплата и бронирование", "3. Betaling en reservering", "3. Payment and booking"],
    ["100% предоплата обязательна. Слот (дата публикации) фиксируется только после оплаты. Без оплаты дата не резервируется.", "100% vooruitbetaling is verplicht. Het tijdslot (de publicatiedatum) wordt pas na betaling vastgelegd. Zonder betaling wordt de datum niet gereserveerd.", "100% upfront payment is required. The slot (publication date) is secured only after payment. The date is not reserved without payment."],
    ["4. Формат размещения", "4. Plaatsingsformaat", "4. Placement format"],
    ["Формат, объём и состав размещения согласовываются отдельно и фиксируются в переписке или инвойсе.", "Het formaat, de omvang en de inhoud van de plaatsing worden afzonderlijk overeengekomen en vastgelegd in correspondentie of op de factuur.", "The format, scope and content of the placement are agreed separately and recorded in correspondence or on the invoice."],
    ["5. Срок размещения", "5. Plaatsingsduur", "5. Placement period"],
    ["Срок размещения определяется текущим форматом. Если срок не зафиксирован отдельно, услуга считается выполненной с момента публикации.", "De plaatsingsduur wordt bepaald door het gekozen formaat. Als geen afzonderlijke termijn is vastgelegd, geldt de dienst als geleverd op het moment van publicatie.", "The placement period is determined by the selected format. If no separate period is specified, the service is deemed completed upon publication."],
    ["6. Публикация и график", "6. Publicatie en planning", "6. Publication and schedule"],
    ["Дата и время публикации могут корректироваться редакцией при необходимости.", "De redactie kan de publicatiedatum en -tijd indien nodig aanpassen.", "The editorial team may adjust the publication date and time if necessary."],
    ["7. Материалы и контент", "7. Materialen en inhoud", "7. Materials and content"],
    ["Материалы предоставляются не позднее чем за 48 часов до публикации. Рекламодатель несёт ответственность за достоверность информации. Редакция вправе адаптировать материалы под формат площадки.", "Materialen moeten uiterlijk 48 uur voor publicatie worden aangeleverd. De adverteerder is verantwoordelijk voor de juistheid van de informatie. De redactie mag het materiaal aanpassen aan het platformformaat.", "Materials must be supplied no later than 48 hours before publication. The advertiser is responsible for the accuracy of the information. The editorial team may adapt materials to the platform format."],
    ["8. Согласование", "8. Goedkeuring", "8. Approval"],
    ["Если рекламодатель не предоставил правки до публикации, материал считается согласованным. После публикации правки не принимаются.", "Als de adverteerder vóór publicatie geen wijzigingen aanlevert, wordt het materiaal als goedgekeurd beschouwd. Na publicatie worden geen wijzigingen meer geaccepteerd.", "If the advertiser does not submit changes before publication, the material is deemed approved. Changes are not accepted after publication."],
    ["9. Удаление и изменение публикаций", "9. Verwijderen en wijzigen van publicaties", "9. Removal and modification of publications"],
    ["Публикации могут быть изменены, архивированы или удалены по усмотрению редакции или в связи с особенностями платформ. Это не является основанием для возврата средств.", "Publicaties kunnen naar het oordeel van de redactie of vanwege platformbeperkingen worden gewijzigd, gearchiveerd of verwijderd. Dit geeft geen recht op terugbetaling.", "Publications may be changed, archived or removed at the editorial team's discretion or due to platform constraints. This does not constitute grounds for a refund."],
    ["10. Результаты и KPI", "10. Resultaten en KPI's", "10. Results and KPIs"],
    ["Мы не гарантируем: количество подписчиков, продажи, заявки. Охваты зависят от алгоритмов платформ.", "Wij garanderen geen aantallen volgers, verkopen of aanvragen. Bereik is afhankelijk van platformalgoritmen.", "We do not guarantee follower numbers, sales or enquiries. Reach depends on platform algorithms."],
    ["11. Отказ от сотрудничества", "11. Annulering door de adverteerder", "11. Withdrawal from cooperation"],
    ["В случае отказа рекламодателя после оплаты возврат средств не производится.", "Als de adverteerder na betaling annuleert, vindt geen terugbetaling plaats.", "If the advertiser cancels after payment, no refund will be provided."],
    ["12. Досрочное прекращение", "12. Voortijdige beëindiging", "12. Early termination"],
    ["Перерасчёт возможен только за неоказанную часть услуг. Фактически выполненные публикации подлежат полной оплате.", "Herberekening is alleen mogelijk voor het niet-geleverde deel van de diensten. Reeds uitgevoerde publicaties zijn volledig verschuldigd.", "Recalculation is possible only for the undelivered portion of services. Publications already completed are payable in full."],
    ["13. Возвраты", "13. Terugbetalingen", "13. Refunds"],
    ["Возврат средств возможен только за неоказанные услуги. Комиссии платёжных систем не возвращаются.", "Terugbetaling is alleen mogelijk voor niet-geleverde diensten. Kosten van betalingsproviders worden niet terugbetaald.", "Refunds are available only for undelivered services. Payment provider fees are non-refundable."],
    ["14. Ответственность сторон", "14. Aansprakelijkheid van partijen", "14. Liability of the parties"],
    ["Рекламодатель несёт ответственность за содержание рекламы. Редакция вправе отказать в размещении без объяснения причин.", "De adverteerder is verantwoordelijk voor de inhoud van de advertentie. De redactie mag een plaatsing zonder opgaaf van reden weigeren.", "The advertiser is responsible for the advertising content. The editorial team may refuse placement without stating a reason."],
    ["15. Платформы и алгоритмы", "15. Platforms en algoritmen", "15. Platforms and algorithms"],
    ["Редакция не несёт ответственность за изменения алгоритмов, охватов или технические ограничения сторонних платформ.", "De redactie is niet aansprakelijk voor wijzigingen in algoritmen, bereik of technische beperkingen van externe platforms.", "The editorial team is not liable for changes in algorithms, reach or technical limitations of third-party platforms."],
    ["16. Использование материалов", "16. Gebruik van materialen", "16. Use of materials"],
    ["Редакция вправе использовать рекламные материалы в портфолио и маркетинговых целях.", "De redactie mag advertentiemateriaal gebruiken voor haar portfolio en marketingdoeleinden.", "The editorial team may use advertising materials in its portfolio and for marketing purposes."],
    ["17. Юридическая информация", "17. Juridische informatie", "17. Legal information"],
    ["Все цены указаны с учётом НДС 21%. К отношениям сторон применяется законодательство Нидерландов.", "Alle prijzen zijn inclusief 21% btw. Op de verhouding tussen partijen is Nederlands recht van toepassing.", "All prices include 21% VAT. The relationship between the parties is governed by Dutch law."],
    ["18. Потребители (физические лица)", "18. Consumenten (particulieren)", "18. Consumers (individuals)"],
    ["Для физических лиц действует право на отзыв договора в течение 14 дней. Выбирая дату публикации и оформляя оплату, вы соглашаетесь на немедленное начало оказания услуги. Если на момент отзыва публикация ещё не вышла — возвращаем уплаченное за неоказанную часть; после полной или частичной публикации возврат за опубликованную часть не производится.", "Consumenten hebben 14 dagen herroepingsrecht. Door een publicatiedatum te kiezen en te betalen, stemt u in met de onmiddellijke uitvoering van de dienst. Als bij herroeping nog niets is gepubliceerd, betalen wij het niet-geleverde deel terug; na gehele of gedeeltelijke publicatie wordt het gepubliceerde deel niet terugbetaald.", "Consumers have a 14-day right of withdrawal. By choosing a publication date and making payment, you agree to immediate performance of the service. If nothing has been published when you withdraw, we refund the undelivered portion; after full or partial publication, the published portion is non-refundable."]
  ];
  legal.forEach(([ru, nl, en]) => { translations[ru] = [nl, en]; });

  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();
  let activeLanguage = "ru";
  let translating = false;

  function normalized(value) { return value.replace(/\s+/g, " ").trim(); }
  function lookup(source, lang) {
    if (lang === "ru") return source;
    const exact = translations[normalized(source)];
    if (exact) return exact[lang === "nl" ? 0 : 1];
    let match = normalized(source).match(/^Шаг\s+(\d+)\s+из\s+6$/);
    if (match) return lang === "nl" ? `Stap ${match[1]} van 6` : `Step ${match[1]} of 6`;
    match = normalized(source).match(/^Выберите\s+(\d+)\s+даты?\.?$/);
    if (match) return lang === "nl" ? `Kies ${match[1]} data${source.trim().endsWith(".") ? "." : ""}` : `Choose ${match[1]} dates${source.trim().endsWith(".") ? "." : ""}`;
    match = normalized(source).match(/^Для этого формата нужно выбрать\s+(\d+)\s+даты?\.$/);
    if (match) return lang === "nl" ? `Voor dit formaat moet u ${match[1]} data kiezen.` : `You need to choose ${match[1]} dates for this format.`;
    match = normalized(source).match(/^Оплатить\s+(.+?)\s+через Mollie\s*→$/);
    if (match) return lang === "nl" ? `Betaal ${match[1]} via Mollie →` : `Pay ${match[1]} via Mollie →`;
    return source;
  }

  function translateTextNode(node) {
    if (!originalText.has(node)) originalText.set(node, node.nodeValue || "");
    const source = originalText.get(node);
    if (!source.trim()) return;
    const leading = source.match(/^\s*/)[0];
    const trailing = source.match(/\s*$/)[0];
    const value = lookup(source, activeLanguage);
    const next = leading + value + trailing;
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
      element.setAttribute(name, lookup(source, activeLanguage));
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
    translating = false;
  }

  function setLanguage(lang, save = true) {
    activeLanguage = SUPPORTED.includes(lang) ? lang : "ru";
    document.documentElement.lang = activeLanguage;
    if (save) { try { localStorage.setItem(STORAGE_KEY, activeLanguage); } catch (_) {} }
    document.querySelectorAll(".pnl-language-switcher button").forEach(button => {
      const selected = button.dataset.lang === activeLanguage;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    const titleSource = "Реклама — Podslushano.nl";
    document.title = lookup(titleSource, activeLanguage);
    const description = document.querySelector('meta[name="description"]');
    if (description) description.content = lookup("Рекламные форматы Podslushano.nl для русскоязычной аудитории Нидерландов.", activeLanguage);
    walk();
  }

  function createSwitcher() {
    const current = document.getElementById(SWITCHER_ID);
    if (current && current.isConnected) return current;
    if (!document.getElementById(STYLE_ID)) {
      const style = document.createElement("style");
      style.id = STYLE_ID;
      style.textContent = `.pnl-language-switcher{position:fixed!important;z-index:2147483647!important;top:14px!important;right:14px!important;display:flex!important;visibility:visible!important;opacity:1!important;transform:none!important;pointer-events:auto!important;gap:3px;padding:4px;border:1px solid rgba(24,24,24,.12);border-radius:999px;background:rgba(255,255,255,.96);box-shadow:0 8px 24px rgba(0,0,0,.12);backdrop-filter:blur(12px)}.pnl-language-switcher button{appearance:none;border:0;border-radius:999px;background:transparent;color:#5d5d5d;font:700 12px/1 system-ui,-apple-system,sans-serif;letter-spacing:.04em;padding:9px 10px;cursor:pointer}.pnl-language-switcher button:hover{color:#151515}.pnl-language-switcher button.active{background:#171717;color:#fff}.pnl-language-switcher button:focus-visible{outline:2px solid #f47721;outline-offset:2px}@media(max-width:720px){.pnl-language-switcher{top:max(8px,env(safe-area-inset-top))!important;right:8px!important}.pnl-language-switcher button{padding:8px 9px}}`;
      document.head.appendChild(style);
    }
    const switcher = document.createElement("div");
    switcher.id = SWITCHER_ID;
    switcher.className = "pnl-language-switcher";
    switcher.setAttribute("role", "group");
    switcher.setAttribute("aria-label", "Language / Taal / Язык");
    switcher.innerHTML = SUPPORTED.map(lang => `<button type="button" data-lang="${lang}">${lang.toUpperCase()}</button>`).join("");
    switcher.addEventListener("click", event => {
      const button = event.target.closest("button[data-lang]");
      if (button) setLanguage(button.dataset.lang);
    });
    document.body.appendChild(switcher);
    return switcher;
  }

  function ensureSwitcher() {
    const switcher = createSwitcher();
    if (!switcher) return;
    switcher.querySelectorAll("button[data-lang]").forEach(button => {
      const selected = button.dataset.lang === activeLanguage;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function initialLanguage() {
    const query = new URLSearchParams(location.search).get("lang");
    if (SUPPORTED.includes(query)) return query;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.includes(stored)) return stored;
    } catch (_) {}
    return "ru";
  }

  function start() {
    ensureSwitcher();
    setLanguage(initialLanguage(), false);
    new MutationObserver(records => {
      if (translating) return;
      records.forEach(record => record.addedNodes.forEach(node => walk(node)));
      ensureSwitcher();
    }).observe(document.documentElement, { childList: true, subtree: true });
    // React can replace the body between observer callbacks during hydration.
    // This inexpensive guard keeps the control available even in that case.
    window.setInterval(ensureSwitcher, 1000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
