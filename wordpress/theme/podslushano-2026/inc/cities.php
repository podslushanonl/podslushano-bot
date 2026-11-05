<?php
/* ---------- City pages: /city/amsterdam/ «Русскоязычные в Амстердаме (Amsterdam)» ----------
 * One page per big city for searches with a city name. It gathers what the site already has:
 * specialists of КонтактGuide in the city (or its province), events there, news that mention the city
 * and the practical guides. Rendered as an ordinary page (route "wp"), so the app shows it as it is. */
if (!defined('ABSPATH')) exit;

/* slug => [name, province as in КонтактGuide, по-русски: именительный, предложный («в …»), родительный («из …»)].
   Латинское название остаётся для поиска по КонтактGuide, афише и новостям; русское — для людей и Google,
   которые ищут «русские в Амстердаме», «русскоязычные в Гааге». */
function pn_cities() {
    return [
        'amsterdam' => ['Amsterdam', 'Noord-Holland', 'Амстердам', 'Амстердаме', 'Амстердама'],
        'rotterdam' => ['Rotterdam', 'Zuid-Holland', 'Роттердам', 'Роттердаме', 'Роттердама'],
        'den-haag' => ['Den Haag', 'Zuid-Holland', 'Гаага', 'Гааге', 'Гааги'],
        'utrecht' => ['Utrecht', 'Utrecht', 'Утрехт', 'Утрехте', 'Утрехта'],
        'eindhoven' => ['Eindhoven', 'Noord-Brabant', 'Эйндховен', 'Эйндховене', 'Эйндховена'],
        'groningen' => ['Groningen', 'Groningen', 'Гронинген', 'Гронингене', 'Гронингена'],
        'tilburg' => ['Tilburg', 'Noord-Brabant', 'Тилбург', 'Тилбурге', 'Тилбурга'],
        'almere' => ['Almere', 'Flevoland', 'Алмере', 'Алмере', 'Алмере'],
        'breda' => ['Breda', 'Noord-Brabant', 'Бреда', 'Бреде', 'Бреды'],
        'nijmegen' => ['Nijmegen', 'Gelderland', 'Неймеген', 'Неймегене', 'Неймегена'],
        'haarlem' => ['Haarlem', 'Noord-Holland', 'Харлем', 'Харлеме', 'Харлема'],
        'arnhem' => ['Arnhem', 'Gelderland', 'Арнем', 'Арнеме', 'Арнема'],
        'amersfoort' => ['Amersfoort', 'Utrecht', 'Амерсфорт', 'Амерсфорте', 'Амерсфорта'],
        'zwolle' => ['Zwolle', 'Overijssel', 'Зволле', 'Зволле', 'Зволле'],
        'leiden' => ['Leiden', 'Zuid-Holland', 'Лейден', 'Лейдене', 'Лейдена'],
        'maastricht' => ['Maastricht', 'Limburg', 'Маастрихт', 'Маастрихте', 'Маастрихта'],
        'enschede' => ['Enschede', 'Overijssel', 'Энсхеде', 'Энсхеде', 'Энсхеде'],
        'delft' => ['Delft', 'Zuid-Holland', 'Делфт', 'Делфте', 'Делфта'],
        'apeldoorn' => ['Apeldoorn', 'Gelderland', 'Апелдорн', 'Апелдорне', 'Апелдорна'],
        'den-bosch' => ['Den Bosch', 'Noord-Brabant', 'Ден Бос', 'Ден Босе', 'Ден Боса'],
    ];
}
function pn_city($slug) {
    $c = pn_cities()[$slug] ?? null;
    return $c ? ['slug' => $slug, 'name' => $c[0], 'prov' => $c[1], 'ru' => $c[2], 'in' => $c[3], 'gen' => $c[4]] : null;
}
function pn_city_title($c) {
    return 'Русскоязычные в ' . $c['in'] . ' (' . $c['name'] . ')';
}
function pn_city_desc($c) {
    return 'Русские и русскоговорящие в ' . $c['in'] . ': врачи, юристы и мастера, которые говорят по-русски, '
        . 'события и новости ' . $c['gen'] . ' на русском, пошаговые справки о жизни в Нидерландах.';
}

function pn_city_page($c) {
    $name = $c['name'];
    $low = mb_strtolower($name);
    $h = '<p class="lead">' . esc_html('Всё для русскоязычных в ' . $c['in'] . ' (' . $name . ') на одной странице: специалисты, которые говорят по-русски, '
        . 'события, новости ' . $c['gen'] . ' на русском и ответы на частые вопросы о жизни в Нидерландах.') . '</p>';

    // Specialists: the city first, then the rest of its province and online ones
    $spec = (array) (pn_specialists() ?: []);
    $in = $prov = [];
    foreach ($spec as $x) {
        if (empty($x['name'])) continue;
        if (mb_strtolower(trim((string) ($x['city'] ?? ''))) === $low) $in[] = $x;
        elseif (($x['province'] ?? '') === $c['prov']) $prov[] = $x;
    }
    $list = array_slice(array_merge($in, $prov), 0, 12);
    $h .= '<h2>Русскоязычные специалисты в ' . esc_html($c['in']) . '</h2>';
    if ($list) {
        $h .= '<ul class="pg-list">';
        foreach ($list as $x) {
            $where = !empty($x['online']) ? 'онлайн' : implode(', ', array_filter([$x['city'] ?? '', $x['province'] ?? '']));
            $h .= '<li><a href="' . esc_url(pn_spec_url($x)) . '"><strong>' . esc_html($x['name']) . '</strong></a> · ' . esc_html((string) ($x['category'] ?? '')) . ($where ? ' · ' . esc_html($where) : '')
                . (!empty($x['description']) ? '<br>' . esc_html(wp_trim_words(wp_strip_all_tags($x['description']), 22, '…')) : '') . '</li>';
        }
        $h .= '</ul>';
    } else {
        $h .= '<p>Пока в КонтактGuide нет карточек из ' . esc_html($c['gen']) . '. Посмотрите специалистов, которые работают онлайн по всей стране.</p>';
    }
    $h .= '<p><a href="' . esc_url(home_url('/guide/')) . '">Все специалисты в КонтактGuide</a> · '
        . '<a href="' . esc_url(home_url('/place/')) . '">Разместить свою карточку</a></p>';

    // Events in the city
    $ev = array_values(array_filter(pn_events(), function ($e) use ($low) { return mb_strtolower(trim((string) ($e['city'] ?? ''))) === $low; }));
    if ($ev) {
        $h .= '<h2>События в ' . esc_html($c['in']) . '</h2><ul class="pg-list">';
        foreach (array_slice($ev, 0, 8) as $e) {
            $h .= '<li><a href="' . esc_url(home_url('/events/' . $e['key'] . '/')) . '">' . esc_html($e['h']) . '</a> · '
                . esc_html(date_i18n('j F', strtotime($e['date'])) . (!empty($e['venue']) ? ', ' . $e['venue'] : '')) . '</li>';
        }
        $h .= '</ul>';
    }

    // News that mention the city (titles in Russian keep Dutch place names in Latin script)
    $news = get_posts(['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => 8, 's' => $name, 'no_found_rows' => true,
        'ignore_sticky_posts' => true]);
    if ($news) {
        $h .= '<h2>Новости ' . esc_html($c['gen']) . ' на русском</h2><ul class="pg-list">';
        foreach ($news as $p) {
            $h .= '<li><a href="' . esc_url(get_permalink($p)) . '">' . esc_html(html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8')) . '</a></li>';
        }
        $h .= '</ul>';
    }

    // Practical guides
    $cat = get_term_by('name', 'Справочник', 'category');
    $guides = $cat ? get_posts(['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => 6, 'cat' => $cat->term_id, 'no_found_rows' => true]) : [];
    if ($guides) {
        $h .= '<h2>Справки для жизни в Нидерландах</h2><ul class="pg-list">';
        foreach ($guides as $p) {
            $h .= '<li><a href="' . esc_url(get_permalink($p)) . '">' . esc_html(html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8')) . '</a></li>';
        }
        $h .= '</ul><p><a href="' . esc_url(pn_spravochnik_url()) . '">Все справки</a></p>';
    }

    // Other cities
    $links = [];
    foreach (pn_cities() as $slug => $x) {
        if ($slug !== $c['slug']) $links[] = '<a href="' . esc_url(home_url('/city/' . $slug . '/')) . '">' . esc_html($x[2]) . '</a>';
    }
    $h .= '<h2>Другие города</h2><p>' . implode(' · ', $links) . '</p>';
    return $h;
}
