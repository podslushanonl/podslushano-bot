<?php
/* ---------- Server-rendered shell for search engines ----------
 * The app draws its sections with JS. Here PHP fills the same shell before it is sent: the current
 * section is visible (class "on"), the article / page / news list / event is already in the HTML,
 * and "#route" links become real addresses. JS then redraws the same places as before. */
if (!defined('ABSPATH')) exit;

function pn_seo_back($href, $label) {
    return '<a class="back" href="' . esc_url(home_url($href)) . '">' . esc_html($label) . '</a>';
}

function pn_seo_news_list($posts) {
    $h = '<ul class="nw-seo">';
    foreach ($posts as $n) {
        // News items carry h/lead, articles (pn_posts('arts')) carry t/blocks
        $t = $n['h'] ?? $n['t'] ?? '';
        $lead = $n['lead'] ?? ($n['blocks'][0][1] ?? '');
        $h .= '<li><a href="' . esc_url($n['link']) . '">' . esc_html($t) . '</a>'
            . ($lead ? ' <span>' . esc_html($lead) . '</span>' : '') . '</li>';
    }
    return $h . '</ul>';
}

function pn_seo_events_list($events) {
    $h = '<ul class="nw-seo">';
    foreach ($events as $e) {
        if (empty($e['key'])) continue;
        $where = implode(', ', array_filter([$e['venue'] ?? '', $e['city'] ?? '']));
        $h .= '<li><a href="' . esc_url(home_url('/events/' . $e['key'] . '/')) . '">' . esc_html($e['h']) . '</a> <span>'
            . esc_html(trim(($e['date'] ?? '') . ($where ? ' · ' . $where : ''))) . '</span></li>';
    }
    return $h . '</ul>';
}

/* ---------- Native hints: one line inside a news article pointing to the section of the site on the same topic ---------- */
function pn_native_hint($cat, $title) {
    $t = mb_strtolower($title . ' ' . $cat);
    $rules = [
        ['налог|belasting|toeslag|бухгалт|zzp|btw', 'coin', 'Нужен бухгалтер или консультант, который говорит по-русски? ', '#guide', 'Найдите в КонтактGuide'],
        ['деньги|цен|топлив|скидк|подорож|дешев|дорож|энерг|страховк', 'coin', 'Где в Нидерландах переплачивают и как сэкономить — ', '#save', 'в разделе «Сэкономить»'],
        ['врач|здоров|huisarts|больниц|стоматолог|страхов|zorg|психолог', 'heart', 'Русскоязычные врачи, стоматологи и психологи в Нидерландах — ', '#guide', 'в КонтактGuide'],
        ['жиль|аренд|huur|ипотек|hypotheek|квартир|дом', 'house', 'Ищете жильё или риелтора? Проверенные площадки — ', '#board', 'в разделе «Работа и жильё»'],
        ['работ|ваканс|uwv|зарплат|увольн', 'briefcase', 'Вакансии с русским и украинским языком — ', '#board', 'в разделе «Работа и жильё»'],
        ['поезд|\bns\b|prorail|транспорт|автобус|метро|трамва', 'pulse', 'Ваша станция: ближайшие поезда, отмены и ремонт — ', '#trains', 'на табло NS'],
        ['погод|дожд|шторм|ветер|снег|жар|knmi', 'cloud', 'Дождь на ближайшие 2 часа и живые камеры городов — ', '#live', 'в разделе «Нидерланды сейчас»'],
        ['концерт|фестивал|культур|музе|театр|выставк|кино', 'ticket', 'Концерты, стендап и фестивали на русском — ', '#events', 'в афише'],
        ['природ|парк|прогул|дюн|лес|пляж', 'walk', 'Гуляем по Нидерландам в небольшой компании — ', '#allo', 'allowalks'],
        ['праздник|рождеств|sinterklaas|подар|день короля', 'gift', 'Подарки и мерч podslushano.nl — ', '/shop/', 'в нашем магазине'],
        ['школ|образован|студент|duo|учёб|детск', 'book', 'Как записать ребёнка в школу или получить studiefinanciering — ', '#spravochnik', 'пошагово в Справочнике'],
    ];
    foreach ($rules as $r) {
        if (preg_match('#' . $r[0] . '#u', $t)) return $r;
    }
    return ['', 'book', 'BSN, DigiD, налоги и пособия пошагово и по-русски — ', '#spravochnik', 'в Справочнике'];
}
function pn_native_insert($html, $cat, $title) {
    if ($cat === 'Справочник' || strpos($html, 'class="native"') !== false) return $html;
    [, $icon, $text, $href, $link] = pn_native_hint($cat, $title);
    if ($href === '#spravochnik') $href = pn_spravochnik_url();
    $hint = '<p class="native"><svg class="ico" aria-hidden="true"><use href="#i-' . $icon . '"/></svg><span>' . esc_html($text)
        . '<a href="' . esc_attr($href) . '">' . esc_html($link) . '</a></span></p>';
    // After the second paragraph, so it reads as part of the article; short texts get it at the end
    $pos = 0;
    for ($i = 0; $i < 2; $i++) {
        $k = strpos($html, '</p>', $pos);
        if ($k === false) return $html . $hint;
        $pos = $k + 4;
    }
    return substr($html, 0, $pos) . $hint . substr($html, $pos);
}
function pn_spravochnik_url() {
    $c = get_term_by('name', 'Справочник', 'category');
    return $c ? get_category_link($c) : home_url('/news/');
}

/* КонтактGuide for search engines: specialists grouped by category (name, place, what they do; contacts stay in the app) */
function pn_seo_specialists($list) {
    $by = [];
    foreach ($list as $x) {
        if (empty($x['name'])) continue;
        $c = trim((string) ($x['category'] ?? '')) ?: 'другое';
        $by[mb_strtoupper(mb_substr($c, 0, 1)) . mb_substr($c, 1)][] = $x;
    }
    ksort($by);
    $h = '';
    foreach ($by as $cat => $items) {
        $h .= '<h2>' . esc_html($cat) . '</h2><ul class="nw-seo">';
        foreach ($items as $x) {
            $where = !empty($x['online']) ? 'онлайн' : implode(', ', array_filter([$x['city'] ?? '', $x['province'] ?? '']));
            $h .= '<li><a href="' . esc_url(pn_spec_url($x)) . '"><strong>' . esc_html($x['name']) . '</strong></a>' . ($where ? ' · ' . esc_html($where) : '')
                . (!empty($x['description']) ? ' <span>' . esc_html(wp_trim_words(wp_strip_all_tags($x['description']), 30, '…')) . '</span>' : '') . '</li>';
        }
        $h .= '</ul>';
    }
    return $h;
}

/* Histories of the 12 provinces (WordPress pages history-province-*) as real links under the map */
function pn_seo_provinces() {
    // All published pages (a few dozen), filtered below: a limit could cut off some of the 12 histories
    $pages = get_posts(['post_type' => 'page', 'post_status' => 'publish', 'posts_per_page' => -1, 'orderby' => 'title', 'order' => 'ASC',
        'no_found_rows' => true]);
    $h = '';
    foreach ($pages as $p) {
        if (strpos($p->post_name, 'history-province-') !== 0) continue;
        $h .= '<li><a href="' . esc_url(get_permalink($p)) . '">' . esc_html(get_the_title($p)) . '</a></li>';
    }
    return $h ? '<nav class="wrap pv-seo" aria-label="История провинций"><h2>История провинций</h2><ul>' . $h . '</ul></nav>' : '';
}

/* Append HTML at the end of a section */
function pn_seo_append($html, $sec, $inner) {
    if ($inner === '') return $html;
    $i = strpos($html, 'id="p-' . $sec . '"');
    if ($i === false) return $html;
    $j = strpos($html, '</section>', $i);
    return $j === false ? $html : substr($html, 0, $j) . $inner . substr($html, $j);
}

/* One H1 in the visible section: add a hidden one from the route title when the section has none */
function pn_seo_h1($html, $sec) {
    $i = strpos($html, '<section class="page on" id="p-' . $sec . '"');
    if ($i === false) return $html;
    $j = strpos($html, '</section>', $i);
    if ($j === false || strpos(substr($html, $i, $j - $i), '<h1') !== false) return $html;
    $m = pn_route_meta($sec);
    if (!$m) return $html;
    $k = strpos($html, '>', $i) + 1;
    return substr($html, 0, $k) . '<h1 class="sr">' . esc_html($m[0]) . '</h1>' . substr($html, $k);
}

function pn_seo_art($n) {
    $img = $n['img'] ? '<figure><img loading="lazy" decoding="async" src="' . esc_url($n['img']) . '" alt="' . esc_attr($n['h']) . '">'
        . ($n['photo_credit'] ? '<figcaption>Фото: ' . esc_html($n['photo_credit']) . '</figcaption>' : '') . '</figure>' : '';
    return pn_seo_back('/news/', 'Новости и статьи')
        . '<article class="na9"><span class="kick"><span class="tag t-acc">' . esc_html($n['cat']) . '</span>'
        . '<time datetime="' . esc_attr($n['date']) . '">' . esc_html(date_i18n('j F Y', strtotime($n['date']))) . '</time></span>'
        . '<h1>' . esc_html($n['h']) . '</h1>' . ($n['lead'] ? '<p class="lead">' . esc_html($n['lead']) . '</p>' : '')
        . $img . '<div class="artbody wpc">' . $n['html'] . '</div></article>';
}

function pn_seo_event($e) {
    $where = implode(', ', array_filter([$e['venue'] ?? '', $e['city'] ?? '']));
    $p = '';
    foreach ((array) ($e['p'] ?? []) as $t) $p .= '<p>' . esc_html(is_array($t) ? implode(' ', $t) : $t) . '</p>';
    return pn_seo_back('/events/', 'Афиша') . '<h1>' . esc_html($e['h']) . '</h1>'
        . '<p>' . esc_html(trim(($e['date'] ?? '') . ' ' . ($e['time'] ?? '')) . ($where ? ' · ' . $where : '')) . '</p>'
        . (!empty($e['s']) ? '<p class="lead">' . esc_html($e['s']) . '</p>' : '') . $p;
}

/** Fill an empty <div id="$id" …></div> of the shell. */
function pn_seo_fill($html, $id, $inner) {
    return preg_replace('#(<div\b[^>]*\bid="' . preg_quote($id, '#') . '"[^>]*>)(</div>)#', '$1' . str_replace(['\\', '$'], ['\\\\', '\\$'], $inner) . '$2', $html, 1);
}

function pn_seo_shell($html, $pn) {
    $route = $pn['route'];
    $sec = $route;
    // The visible section
    $html = preg_replace('#<section class="page" id="p-' . preg_quote($sec, '#') . '"#', '<section class="page on" id="p-' . $sec . '"', $html, 1);
    // Home: one heading for the page, readable by screen readers too
    $html = preg_replace('#(<section class="page( on)?" id="p-home"[^>]*>)#', '$1<h1 class="sr">podslushano.nl — русскоязычное сообщество в Нидерландах: новости, специалисты, справки, афиша</h1>', $html, 1);
    if ($route === 'art' && !empty($pn['post'])) $html = pn_seo_fill($html, 'artBody', pn_seo_art($pn['post']));
    if ($route === 'wp' && !empty($pn['page'])) {
        $html = pn_seo_fill($html, 'wpBody', pn_seo_back('/', 'Главная') . '<h1>' . esc_html($pn['page']['title']) . '</h1>' . $pn['page']['html']);
    }
    if ($route === 'event' && ($e = pn_event($pn['param'] ?? ''))) $html = pn_seo_fill($html, 'evDet', pn_seo_event($e));
    if ($route === 'events') $html = pn_seo_fill($html, 'evGrid', pn_seo_events_list($pn['events'])
        . (!empty($pn['past']) ? '<h2>Прошедшие</h2>' . pn_seo_events_list($pn['past']) : ''));
    if ($route === 'news' && !empty($pn['term'])) {
        // Category page: its name as the heading, its own description and posts
        $html = preg_replace('#(<section class="page on" id="p-news".*?<h1 class="st">)[^<]*(</h1>)#s', '${1}' . esc_html($pn['term']['name']) . '$2', $html, 1);
        $html = pn_seo_fill($html, 'newsBody', ($pn['term']['desc'] ? '<p class="lead">' . esc_html($pn['term']['desc']) . '</p>' : '') . pn_seo_news_list($pn['posts']));
    } elseif ($route === 'news') $html = pn_seo_fill($html, 'newsBody', pn_seo_news_list(array_merge($pn['posts'], pn_posts('arts'))));
    if ($route === 'home') $html = pn_seo_fill($html, 'homeNews', pn_seo_news_list(array_slice($pn['posts'], 0, 8)));
    if ($route === 'guide' && !empty($pn['spec'])) $html = pn_seo_fill($html, 'gGrid', pn_seo_specialists($pn['spec']));
    if ($route === 'provinces') $html = pn_seo_append($html, 'provinces', pn_seo_provinces());
    if ($route === 'allo') $html = pn_seo_fill($html, 'awRoot', '<p>allowalks: прогулки по Нидерландам в небольшой компании на русском языке, '
        . 'маршруты по городам и природе, подарочные карты.</p>');
    $html = str_replace('href="#spravochnik"', 'href="' . esc_url(pn_spravochnik_url()) . '"', $html);
    // A section without its own heading (allowalks) still gets one H1 for search engines and screen readers
    $html = pn_seo_h1($html, $sec);
    // "#route" links → real addresses (JS keeps them fast: it catches the click and switches the section)
    $map = ['home' => '/', 'links' => '/links/'];
    foreach (pn_routes() as $slug => $r) $map[$r] = '/' . $slug . '/';
    return preg_replace_callback('#href="\#([a-z0-9-]+)"#', function ($m) use ($map) {
        if (!isset($map[$m[1]])) return $m[0];
        return 'href="' . esc_url(home_url($map[$m[1]])) . '" data-hash="' . $m[1] . '"';
    }, $html);
}

/* ---------- Structured data: events for Google (Event rich results) ---------- */
function pn_seo_iso($date, $time) {
    if (!$date) return '';
    try {
        $d = new DateTime($date . ' ' . ($time ?: '00:00'), new DateTimeZone('Europe/Amsterdam'));
    } catch (Exception $x) {
        return '';
    }
    return $time ? $d->format('c') : $d->format('Y-m-d');
}
function pn_seo_event_ld($e) {
    $start = pn_seo_iso($e['date'] ?? '', $e['time'] ?? '');
    if (!$start || empty($e['h'])) return null;
    $url = home_url('/events/' . $e['key'] . '/');
    $desc = ($e['s'] ?? '') ?: implode(' ', array_slice((array) ($e['p'] ?? []), 0, 2));
    $ld = ['@context' => 'https://schema.org', '@type' => 'Event', 'name' => $e['h'], 'startDate' => $start, 'url' => $url,
        'eventStatus' => 'https://schema.org/EventScheduled', 'description' => wp_strip_all_tags((string) $desc)];
    if (!empty($e['end'])) $ld['endDate'] = pn_seo_iso($e['end'], '');
    if (!empty($e['venue']) || !empty($e['addr']) || !empty($e['city'])) {
        $ld['eventAttendanceMode'] = 'https://schema.org/OfflineEventAttendanceMode';
        $ld['location'] = ['@type' => 'Place', 'name' => ($e['venue'] ?? '') ?: ($e['city'] ?? ''),
            'address' => array_filter(['@type' => 'PostalAddress', 'streetAddress' => $e['addr'] ?? '', 'addressLocality' => $e['city'] ?? ''])];
    } else {
        $ld['eventAttendanceMode'] = 'https://schema.org/OnlineEventAttendanceMode';
        $ld['location'] = ['@type' => 'VirtualLocation', 'url' => ($e['url'] ?? '') ?: $url];
    }
    if (!empty($e['img'])) $ld['image'] = [preg_match('#^https?://#', $e['img']) ? $e['img'] : home_url($e['img'])];
    if (!empty($e['org'])) $ld['organizer'] = ['@type' => 'Organization', 'name' => $e['org']];
    if (!empty($e['lang'])) $ld['inLanguage'] = $e['lang'] === 'русский' ? 'ru' : $e['lang'];
    $offer = ['@type' => 'Offer', 'url' => ($e['url'] ?? '') ?: $url, 'priceCurrency' => 'EUR',
        'availability' => pn_upcoming($e) ? 'https://schema.org/InStock' : 'https://schema.org/SoldOut'];
    if (preg_match('/(\d+(?:[.,]\d+)?)/', (string) ($e['price'] ?? ''), $m)) $offer['price'] = str_replace(',', '.', $m[1]);
    elseif (preg_match('/бесплатн|free|gratis/iu', (string) ($e['price'] ?? ''))) $offer['price'] = '0';
    $ld['offers'] = $offer;
    return $ld;
}
add_action('wp_head', function () {
    $r = get_query_var('pn_route');
    $list = [];
    if ($r === 'event' && ($e = pn_event(get_query_var('pn_key')))) $list = [$e];
    elseif ($r === 'events') $list = array_slice(pn_events(), 0, 30);
    foreach ($list as $e) {
        if ($ld = pn_seo_event_ld($e)) {
            echo '<script type="application/ld+json">' . wp_json_encode($ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG) . '</script>' . "\n";
        }
    }
}, 5);

/* ---------- Google News: news posts are NewsArticle, and /news-sitemap.xml lists the last two days ---------- */
function pn_is_news_post($p) {
    $arts = pn_art_cat_ids();
    return !$arts || !has_category($arts, $p);
}
add_filter('wpseo_schema_article_type', function ($type) {
    return is_singular('post') && pn_is_news_post(get_queried_object()) ? 'NewsArticle' : $type;
});
function pn_news_sitemap_xml() {
    $args = ['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => 1000, 'ignore_sticky_posts' => true,
        'no_found_rows' => true, 'date_query' => [['after' => '2 days ago']]];
    if ($arts = pn_art_cat_ids()) $args['category__not_in'] = $arts;
    $xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">';
    foreach (get_posts($args) as $p) {
        $xml .= '<url><loc>' . esc_url(get_permalink($p)) . '</loc><news:news><news:publication><news:name>podslushano.nl</news:name>'
            . '<news:language>ru</news:language></news:publication><news:publication_date>' . esc_html(get_post_time('c', true, $p))
            . '</news:publication_date><news:title>' . esc_html(html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8'))
            . '</news:title></news:news></url>';
    }
    return $xml . '</urlset>';
}
// Served by Yoast (it owns every *-sitemap.xml address), next to /pn-pages-sitemap.xml
add_action('init', function () {
    global $wpseo_sitemaps;
    if (empty($wpseo_sitemaps) || !method_exists($wpseo_sitemaps, 'register_sitemap')) return;
    $wpseo_sitemaps->register_sitemap('news', function () {
        global $wpseo_sitemaps;
        $wpseo_sitemaps->set_sitemap(pn_news_sitemap_xml());
    });
}, 20);
add_filter('wpseo_sitemap_index', function ($x) {
    return $x . '<sitemap><loc>' . esc_url(home_url('/news-sitemap.xml')) . '</loc></sitemap>';
});

/* ---------- Practical guides: their «Частые вопросы» block as FAQPage ---------- */
add_action('wp_head', function () {
    if (!is_singular('post')) return;
    $html = (string) get_post_field('post_content', get_queried_object_id());
    if (strpos($html, 'pg-faq-i') === false) return;
    preg_match_all('#<details class="pg-faq-i"><summary>(.*?)</summary><div>(.*?)</div></details>#s', $html, $m, PREG_SET_ORDER);
    $q = [];
    foreach ($m as $x) {
        $name = trim(html_entity_decode(wp_strip_all_tags($x[1]), ENT_QUOTES, 'UTF-8'));
        $text = trim(html_entity_decode(wp_strip_all_tags($x[2]), ENT_QUOTES, 'UTF-8'));
        if ($name && $text) $q[] = ['@type' => 'Question', 'name' => $name, 'acceptedAnswer' => ['@type' => 'Answer', 'text' => $text]];
    }
    if (!$q) return;
    echo '<script type="application/ld+json">' . wp_json_encode(['@context' => 'https://schema.org', '@type' => 'FAQPage', 'mainEntity' => $q],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG) . '</script>' . "\n";
}, 5);
