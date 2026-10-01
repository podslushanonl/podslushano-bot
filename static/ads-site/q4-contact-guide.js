(() => {
  const GUIDE_PRICES = {
    standardMonth: '€7,39',
    standardYear: '€73,26',
    premiumMonth: '€14,79',
    premiumSix: '€80,66',
    premiumYear: '€147,26'
  };

  function fixExpertLive() {
    const card = document.querySelector('[data-product-card="ad_expert_live"]');
    if (card) {
      const stories = [...card.querySelectorAll('.include')].find(el => /Stories/.test(el.textContent || ''));
      if (stories) stories.textContent = '4 Stories для набора участников';
    }
    const table = document.querySelector('#compare table');
    if (table) {
      const row = [...table.querySelectorAll('tbody tr')].find(tr => {
        const first = tr.querySelector('td');
        return first && first.textContent.trim() === 'Stories';
      });
      if (row && row.children[3]) row.children[3].textContent = '4';
    }
  }

  function fixCampaignCopy() {
    const seasonCopy = document.querySelector('.season-panel p');
    if (seasonCopy) {
      seasonCopy.textContent = 'Обычно одно письмо в начале месяца: новые форматы, сезонные предложения, свободные даты и важные обновления. Иногда можем отправить ещё одно письмо по отдельному важному поводу — максимум 2 письма в месяц. Скидка действует на все рекламные форматы, включая Contact Guide, до 31 декабря 2026 года.';
    }

    const guide = document.querySelector('#guide .guide');
    if (guide) {
      const paragraph = guide.querySelector('p');
      if (paragraph) {
        paragraph.textContent = 'Карточка специалиста или бизнеса в поиске нашего Telegram-бота. Скидка −26% распространяется на все тарифы Contact Guide. Чтобы бот применил её автоматически, укажите тот же e-mail, который использовали для подписки на рекламные обновления. В формате «Под ключ» Premium уже включён на 2 месяца.';
      }
    }

    const faq = [...document.querySelectorAll('.faq details')].find(item => {
      const summary = item.querySelector('summary');
      return summary && summary.textContent.includes('Как получить скидку');
    });
    if (faq) {
      const paragraph = faq.querySelector('p');
      if (paragraph) {
        paragraph.textContent = 'Нажмите на подарок, оставьте e-mail и подтвердите подписку на обновления для рекламодателей. После этого −26% применяется ко всем рекламным форматам, включая Contact Guide. В Contact Guide укажите тот же e-mail для factuur — бот узнает подписку и пересчитает сумму перед Mollie.';
      }
    }

    const giftCard = document.querySelector('#giftShell .gift-card');
    if (giftCard) {
      const paragraph = giftCard.querySelector(':scope > p');
      if (paragraph) {
        paragraph.textContent = 'Подпишитесь на обновления для рекламодателей Podslushano.nl и получите −26% на все рекламные форматы, включая Contact Guide. Обычно отправляем одно письмо в начале месяца. При отдельной важной акции или свободном рекламном слоте можем отправить ещё одно — максимум 2 письма в месяц. Отписаться можно в любой момент.';
      }

      const consentText = giftCard.querySelector('.consent span');
      if (consentText) {
        consentText.textContent = 'Я согласен(на) получать рекламные и информационные обновления Podslushano.nl. Обычно 1 письмо в месяц, максимум 2 при отдельном важном поводе.';
      }

      const form = giftCard.querySelector('#giftForm');
      if (form && !giftCard.querySelector('[data-newsletter-rule-note]')) {
        const note = document.createElement('div');
        note.dataset.newsletterRuleNote = '1';
        note.className = 'small-note';
        note.textContent = 'Без спама и повторных напоминаний. В каждом письме будет ссылка для отписки; после отписки рекламные письма больше не отправляем.';
        form.appendChild(note);
      }
    }

    const faqWrap = document.querySelector('.faq');
    if (faqWrap && !faqWrap.querySelector('[data-newsletter-faq]')) {
      const details = document.createElement('details');
      details.dataset.newsletterFaq = '1';
      details.innerHTML = '<summary>Как часто приходит рассылка?</summary><p>Обычно один раз в месяц. Дополнительное письмо отправляем только по отдельному важному поводу — например, при специальной акции или освободившейся рекламной дате. Максимум 2 письма в месяц. В каждом письме будет возможность отписаться.</p>';
      faqWrap.appendChild(details);
    }
  }

  function guideUnlocked() {
    return Boolean(document.getElementById('giftFab')?.classList.contains('unlocked'));
  }

  function renderGuideDiscount() {
    const guide = document.querySelector('#guide .guide');
    if (!guide) return;
    const boxes = guide.querySelectorAll('.guide-box');
    const button = guide.querySelector('a.button');
    const active = guideUnlocked();

    if (boxes[0]) {
      const strong = boxes[0].querySelector('strong');
      const span = boxes[0].querySelector('span');
      if (strong) strong.innerHTML = active ? '<s style="font-size:15px;color:#78867f;font-weight:600">€9,99</s> ' + GUIDE_PRICES.standardMonth : '€9,99';
      if (span) span.innerHTML = active
        ? '1 месяц · обычная позиция<br><s>€99</s> → <b>' + GUIDE_PRICES.standardYear + '</b> / год'
        : '1 месяц · обычная позиция<br>€99 / год';
    }

    if (boxes[1]) {
      const strong = boxes[1].querySelector('strong');
      const span = boxes[1].querySelector('span');
      if (strong) strong.innerHTML = active ? '<s style="font-size:15px;color:#78867f;font-weight:600">€19,99</s> ' + GUIDE_PRICES.premiumMonth : '€19,99';
      if (span) span.innerHTML = active
        ? '1 месяц · фото/логотип · бейдж 🌟<br><s>€109</s> → <b>' + GUIDE_PRICES.premiumSix + '</b> / 6 мес · <s>€199</s> → <b>' + GUIDE_PRICES.premiumYear + '</b> / год'
        : '1 месяц · фото/логотип · бейдж 🌟 · выше Standard<br>€109 / 6 мес · €199 / год';
    }

    if (button) {
      button.textContent = active ? 'Добавить со скидкой −26% →' : 'Добавить себя в Contact Guide →';
    }
  }

  fixExpertLive();
  fixCampaignCopy();
  renderGuideDiscount();

  const giftFab = document.getElementById('giftFab');
  if (giftFab) {
    new MutationObserver(renderGuideDiscount).observe(giftFab, {
      attributes: true,
      attributeFilter: ['class']
    });
  }
})();
