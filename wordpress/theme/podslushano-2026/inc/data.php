<?php
/** Live data for the app: weather, specialists, posts. Everything is cached. */
if (!defined('ABSPATH')) exit;

function pn_http_json($url, $timeout = 6) {
    $r = wp_remote_get($url, ['timeout' => $timeout, 'headers' => ['Accept' => 'application/json']]);
    if (is_wp_error($r) || wp_remote_retrieve_response_code($r) !== 200) return null;
    $j = json_decode(wp_remote_retrieve_body($r), true);
    return is_array($j) ? $j : null;
}

/* Remembers the last good value so a failing source never empties the site. */
function pn_cached($key, $ttl, $fn) {
    $v = get_transient($key);
    if ($v !== false) return $v;
    $v = $fn();
    if ($v) {
        set_transient($key, $v, $ttl);
        update_option($key . '_last', $v, false);
        return $v;
    }
    set_transient($key, get_option($key . '_last') ?: [], 120);
    return get_option($key . '_last') ?: null;
}

/* ---------- weather: Buienradar ---------- */
function pn_wx_kind($icon) {
    $c = strtolower(preg_replace('/\..*$/', '', basename((string) $icon)));
    $map = ['a' => 'clear', 'aa' => 'clear', 'b' => 'partly', 'bb' => 'partly', 'j' => 'partly', 'jj' => 'partly',
        'c' => 'cloud', 'cc' => 'cloud', 'q' => 'rain', 'qq' => 'rain', 'f' => 'shower', 'ff' => 'shower',
        'm' => 'rain', 'mm' => 'rain', 'g' => 'storm', 'gg' => 'storm', 's' => 'storm', 'ss' => 'storm',
        'u' => 'snow', 'uu' => 'snow', 'v' => 'snow', 'vv' => 'snow', 'w' => 'rain', 'ww' => 'rain', 'd' => 'cloud', 'dd' => 'cloud'];
    return $map[$c] ?? 'cloud';
}
function pn_wx_desc($nl, $kind) {
    $d = [
        'Zwaar bewolkt en regen' => 'Пасмурно, дождь', 'Vrijwel onbewolkt (zonnig/helder)' => 'Ясно',
        'Zwaar bewolkt' => 'Пасмурно', 'Afwisselend bewolkt met (mogelijk) wat lichte regen' => 'Переменная облачность, небольшой дождь',
        'Mix van opklaringen en middelbare of lage bewolking' => 'Переменная облачность', 'Half bewolkt' => 'Облачно с прояснениями',
        'Licht bewolkt' => 'Малооблачно', 'Zonnig' => 'Солнечно', 'Mist' => 'Туман', 'Motregen' => 'Морось',
        'Opklaringen en kans op enkele pittige (onweers)buien' => 'Прояснения, возможны ливни с грозой',
    ];
    if (isset($d[$nl])) return $d[$nl];
    $k = ['clear' => 'Ясно', 'partly' => 'Переменная облачность', 'cloud' => 'Облачно', 'rain' => 'Дождь',
        'shower' => 'Ливни', 'storm' => 'Гроза', 'snow' => 'Снег'];
    return $k[$kind] ?? 'Облачно';
}
function pn_weather() {
    return pn_cached('pn_wx', 10 * MINUTE_IN_SECONDS, function () {
        $br = pn_http_json('https://data.buienradar.nl/2.0/feed/json', 8);
        if (!$br || empty($br['actual']['stationmeasurements'])) return null;
        $C = [
            'Amsterdam' => ['Amsterdam', 'Schiphol', 52.37, 4.90], 'Rotterdam' => ['Rotterdam', 'Rotterdam', 51.92, 4.48],
            'Den Haag' => ['Den Haag', 'Hoek van Holland', 52.08, 4.30], 'Utrecht' => ['Utrecht', 'De Bilt', 52.09, 5.12],
            'Eindhoven' => ['Eindhoven', 'Eindhoven', 51.44, 5.48], 'Groningen' => ['Groningen', 'Groningen', 53.22, 6.57],
            'Maastricht' => ['Maastricht', 'Maastricht', 50.85, 5.69], 'Arnhem' => ['Arnhem', 'Arnhem', 51.98, 5.91],
            'Tilburg' => ['Tilburg', 'Gilze Rijen', 51.56, 5.09], 'Leeuwarden' => ['Leeuwarden', 'Leeuwarden', 53.20, 5.80],
            'Nijmegen' => ['Nijmegen', 'Arnhem', 51.84, 5.86],
        ];
        $st = $br['actual']['stationmeasurements'];
        $cities = [];
        foreach ($C as $nl => [$ru, $station, $lat, $lon]) {
            $s = null;
            foreach ($st as $x) if (stripos($x['stationname'] ?? '', $station) !== false) { $s = $x; break; }
            if (!$s) continue;
            $rain = [];
            $r = wp_remote_get("https://gpsgadget.buienradar.nl/data/raintext?lat=$lat&lon=$lon", ['timeout' => 3]);
            if (!is_wp_error($r)) {
                foreach (preg_split('/\r?\n/', trim(wp_remote_retrieve_body($r))) as $line) {
                    $p = explode('|', trim($line));
                    if (count($p) === 2) $rain[] = [intval($p[0]), $p[1]];
                }
            }
            $k = pn_wx_kind($s['iconurl'] ?? '');
            $cities[] = ['nl' => $nl, 'ru' => $ru, 'st' => str_replace('Meetstation ', '', $s['stationname']),
                't' => $s['temperature'] ?? null, 'f' => $s['feeltemperature'] ?? ($s['temperature'] ?? null),
                'd' => pn_wx_desc($s['weatherdescription'] ?? '', $k), 'k' => $k, 'w' => $s['windspeedBft'] ?? 0,
                'wd' => $s['winddirection'] ?? '', 'h' => $s['humidity'] ?? 0, 'rain' => $rain];
        }
        if (!$cities) return null;
        $fc = [];
        foreach (($br['forecast']['fivedayforecast'] ?? []) as $x) {
            $k = pn_wx_kind($x['iconurl'] ?? '');
            $fc[] = ['day' => substr($x['day'], 0, 10), 'min' => $x['mintemperatureMin'] ?? null, 'max' => $x['maxtemperatureMax'] ?? null,
                'rc' => $x['rainChance'] ?? 0, 'd' => pn_wx_desc($x['weatherdescription'] ?? '', $k), 'k' => $k];
        }
        $report = '';
        if ($fc) {
            $mx = max(array_column($fc, 'max'));
            $wet = array_filter($fc, function ($f) { return $f['rc'] >= 60; });
            $report = 'ближайшие пять дней до ' . round($mx) . '°' . ($wet ? ', дождливых дней: ' . count($wet) : ', почти без дождя');
        }
        $a = $br['actual'];
        return ['at' => $st[0]['timestamp'] ?? current_time('c'), 'sunrise' => substr($a['sunrise'] ?? '', 11, 5),
            'sunset' => substr($a['sunset'] ?? '', 11, 5), 'cities' => $cities, 'fc' => $fc, 'report' => $report];
    });
}

/* ---------- specialists: bot API ---------- */
function pn_specialists() {
    return pn_cached('pn_spec', 15 * MINUTE_IN_SECONDS, function () {
        $j = pn_http_json(PN_BOT . '/api/specialists.json', 8);
        if (!$j) return null;
        $list = $j['specialists'] ?? (array_is_list($j) ? $j : null);
        return (is_array($list) && count($list) > 10) ? $list : null;
    });
}
if (!function_exists('array_is_list')) {
    function array_is_list($a) { return $a === [] || array_keys($a) === range(0, count($a) - 1); }
}

/* ---------- posts ---------- */
function pn_art_cat_ids() {
    $ids = [];
    // Статьи редакции и практические справки бота (utils/site_guides.py, рубрика «Справочник»)
    foreach (['stati', 'statyi', 'articles', 'stati-ru', 'spravochnik'] as $slug) {
        $c = get_category_by_slug($slug);
        if ($c) $ids[] = $c->term_id;
    }
    foreach (['Статьи', 'Справочник'] as $name) {
        $c = get_term_by('name', $name, 'category');
        if ($c) $ids[] = $c->term_id;
    }
    return array_unique($ids);
}
function pn_post_item($p, $full = false) {
    $cats = get_the_category($p->ID);
    $cat = $cats ? $cats[0]->name : 'Новости';
    if ($cat === 'Uncategorized' || $cat === 'Без рубрики') $cat = 'Новости';
    $thumb = get_post_thumbnail_id($p->ID);
    $lead = has_excerpt($p->ID) ? get_the_excerpt($p) : wp_trim_words(wp_strip_all_tags($p->post_content), 32, '…');
    $it = ['id' => $p->post_name, 'link' => get_permalink($p), 'date' => get_the_date('Y-m-d', $p), 'time' => get_the_date('H:i', $p),
        'cat' => $cat, 'h' => html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8'), 'lead' => html_entity_decode($lead, ENT_QUOTES, 'UTF-8'),
        'img' => $thumb ? (wp_get_attachment_image_url($thumb, 'large') ?: '') : '',
        'thumb' => $thumb ? (wp_get_attachment_image_url($thumb, 'thumbnail') ?: '') : '',
        'photo_credit' => $thumb ? wp_strip_all_tags(wp_get_attachment_caption($thumb) ?: '') : ''];
    if ($full) $it['html'] = apply_filters('the_content', $p->post_content);
    return $it;
}
function pn_posts($type = 'news', $n = 24) {
    $arts = pn_art_cat_ids();
    $args = ['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => $n, 'ignore_sticky_posts' => true, 'no_found_rows' => true];
    if ($type === 'arts') {
        if (!$arts) return [];
        $args['category__in'] = $arts;
    } elseif ($arts) {
        $args['category__not_in'] = $arts;
    }
    $out = [];
    foreach (get_posts($args) as $p) {
        $it = pn_post_item($p);
        if ($type === 'arts') $out[] = ['id' => $it['id'], 'link' => $it['link'], 'cat' => $it['cat'], 't' => $it['h'], 'blocks' => [['p', $it['lead']]]];
        else $out[] = $it;
    }
    return $out;
}

/* ---------- Афиша, вакансии, партнёры: wp-admin (inc/content.php), the theme JSON while a type has no entries ---------- */
function pn_today() {
    return (new DateTime('now', new DateTimeZone('Europe/Amsterdam')))->format('Y-m-d');
}
function pn_theme_json($file) {
    $j = json_decode((string) @file_get_contents(PN_DIR . '/data/' . $file), true);
    return is_array($j) ? $j : [];
}
function pn_has_entries($type) {
    $c = wp_count_posts($type);
    return $c && !empty($c->publish);
}
function pn_entries($type, $args = []) {
    return get_posts($args + ['post_type' => $type, 'post_status' => 'publish', 'posts_per_page' => -1, 'no_found_rows' => true, 'suppress_filters' => false]);
}
function pn_m($id, $k) {
    return (string) get_post_meta($id, '_pn_' . $k, true);
}
function pn_thumb($id) {
    $t = get_post_thumbnail_id($id);
    return $t ? (string) (wp_get_attachment_image_url($t, 'large') ?: '') : '';
}
/* Theme image: "ev-sorokin" or "img/ev-sorokin.webp" -> URL of assets/img/<file>. */
function pn_asset_img($img) {
    if (!$img) return '';
    if (preg_match('#^(https?:)?//|^/#', $img)) return $img;
    $f = basename($img);
    if (strpos($f, '.') === false) {
        foreach (['webp', 'jpg', 'png'] as $ext) if (file_exists(PN_DIR . '/assets/img/' . $f . '.' . $ext)) return PN_URI . '/assets/img/' . $f . '.' . $ext;
        return '';
    }
    return file_exists(PN_DIR . '/assets/img/' . $f) ? PN_URI . '/assets/img/' . $f : '';
}
/* Editor content -> plain paragraphs (the app escapes and wraps them). */
function pn_paragraphs($content) {
    $html = wpautop(preg_replace('/<!--.*?-->/s', '', (string) $content));
    preg_match_all('#<(p|h[1-6]|li|blockquote)\b[^>]*>(.*?)</\1>#si', $html, $m);
    $out = [];
    foreach ($m[2] as $x) {
        $t = trim(html_entity_decode(wp_strip_all_tags(preg_replace('#<br\s*/?>#i', "\n", $x)), ENT_QUOTES, 'UTF-8'));
        if ($t !== '') $out[] = $t;
    }
    return $out;
}
function pn_title($p) {
    return html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8');
}

/* Event in the shape of the EV items of events_bundle.json; img is a URL. */
function pn_event_item($p) {
    $id = $p->ID;
    $e = ['key' => $p->post_name, 'h' => pn_title($p)];
    foreach (['s', 'date', 'time', 'doors', 'venue', 'addr', 'city', 'price', 'org', 'age', 'lang'] as $k) $e[$k] = pn_m($id, $k);
    $e['img'] = pn_thumb($id);
    $e['url'] = pn_m($id, 'url');
    $e['p'] = pn_paragraphs($p->post_content);
    $e['note'] = pn_m($id, 'note');
    $e['cat'] = pn_m($id, 'cat') ?: 'концерт';
    $e['end'] = pn_m($id, 'end');
    $e['partner'] = pn_m($id, 'partner') === '1';
    $e['pos'] = pn_m($id, 'pos');
    $tix = [];
    foreach (preg_split('/\r?\n/', pn_m($id, 'tickets')) as $line) {
        $c = array_map('trim', explode('|', $line));
        if ($c[0] === '') continue;
        $tix[] = [$c[0], $c[1] ?? '', $c[2] ?? ''];
    }
    if ($tix) $e['tickets'] = $tix;
    return $e;
}
function pn_upcoming($e) {
    return !empty($e['date']) && ((!empty($e['end']) ? $e['end'] : $e['date']) >= pn_today());
}
function pn_sort_events(&$list) {
    usort($list, function ($a, $b) { return strcmp($a['date'] . ' ' . $a['time'], $b['date'] . ' ' . $b['time']); });
}
/* Upcoming events: Афиша in wp-admin, or data/events.json while it has no published entries. */
/* Paid events from organisers (submitted on the site or in the bot, approved by the team). */
/* Events from the bot: paid ones after review and the ones the editor adds in the bot.
   «hidden» are keys of theme events the editor removed in the bot. */
function pn_bot_afisha() {
    return pn_cached('pn_user_ev2', 10 * MINUTE_IN_SECONDS, function () {
        $j = pn_http_json(PN_BOT . '/api/afisha/events', 6);
        if (!$j || !isset($j['events']) || !is_array($j['events'])) return null;
        return ['list' => $j['events'], 'hidden' => array_values(array_filter((array) ($j['hidden'] ?? []), 'is_string'))];
    });
}
function pn_user_events() {
    $j = pn_bot_afisha();
    $out = [];
    foreach (($j['list'] ?? []) as $e) {
        if (!is_array($e) || empty($e['key']) || empty($e['date'])) continue;
        $out[] = $e + ['h' => '', 's' => '', 'time' => '', 'venue' => '', 'city' => '', 'img' => '', 'url' => '', 'p' => [], 'cat' => 'событие', 'end' => ''];
    }
    return $out;
}
function pn_all_events() {
    static $ev = null;
    if ($ev !== null) return $ev;
    if (pn_has_entries('pn_event')) {
        $ev = array_map('pn_event_item', pn_entries('pn_event'));
    } else {
        $ev = array_map(function ($e) { $e['img'] = pn_asset_img($e['img'] ?? ''); return $e; }, pn_theme_json('events.json'));
    }
    $hidden = (array) (pn_bot_afisha()['hidden'] ?? []);
    if ($hidden) $ev = array_values(array_filter($ev, function ($e) use ($hidden) { return !in_array($e['key'] ?? '', $hidden, true); }));
    $ev = array_merge($ev, pn_user_events());
    pn_sort_events($ev);
    return $ev;
}
function pn_events() {
    return array_values(array_filter(pn_all_events(), 'pn_upcoming'));
}
/* Past events for «Прошедшие» at the bottom of the Афиша: newest first. The date decides by itself (Amsterdam time). */
function pn_past_events($n = 12) {
    $past = array_values(array_filter(pn_all_events(), function ($e) { return !empty($e['date']) && !pn_upcoming($e); }));
    return array_slice(array_reverse($past), 0, $n);
}
/* Past events keep their pages (they are in Google and in shared links), marked as past by the app. */
function pn_event($key) {
    foreach (pn_all_events() as $e) if (($e['key'] ?? '') === $key) return $e;
    return null;
}
/* Events for /links/ (shape of data/links.json events): entries with «Показывать на /links/». */
function pn_links_events() {
    if (!pn_has_entries('pn_event')) {
        $L = array_map(function ($e) { $e['img'] = pn_asset_img($e['img'] ?? ''); return $e; }, pn_theme_json('links.json')['events'] ?? []);
        // Events removed in the bot leave /links/ too (links.json has no keys, so match by title)
        $hidden = (array) (pn_bot_afisha()['hidden'] ?? []);
        $gone = [];
        foreach (pn_theme_json('events.json') as $e) if (in_array($e['key'] ?? '', $hidden, true)) $gone[] = $e['h'] ?? '';
        return array_values(array_filter($L, function ($e) use ($gone) { return ($e['d'] ?? '') >= pn_today() && !in_array($e['h'] ?? '', $gone, true); }));
    }
    $L = [];
    foreach (pn_entries('pn_event', ['meta_key' => '_pn_links', 'meta_value' => '1']) as $p) {
        $e = pn_event_item($p);
        if (!pn_upcoming($e) || !$e['img']) continue;
        $where = trim(explode(',', $e['venue'])[0]);
        $L[] = ['d' => $e['date'], 'h' => $e['h'], 's' => implode(', ', array_filter([$where, $e['city']])), 'url' => $e['url'] ?: home_url('/events/' . $e['key'] . '/'),
            'img' => $e['img'], 'pos' => $e['pos'], 't' => $e['date'] . ' ' . $e['time']];
    }
    usort($L, function ($a, $b) { return strcmp($a['t'], $b['t']); });
    return array_map(function ($e) { unset($e['t']); return $e; }, $L);
}

/* Jobs (shape of jobs11.json "jobs"): Вакансии in wp-admin, newest first; expired («Показывать до») are left out. */
function pn_jobs() {
    $today = pn_today();
    if (!pn_has_entries('pn_job')) return pn_theme_json('jobs.json');
    $L = [];
    foreach (pn_entries('pn_job') as $p) {
        $id = $p->ID;
        $until = pn_m($id, 'until');
        if ($until && $until < $today) continue;
        $L[] = ['id' => $p->post_name, 'title' => pn_title($p), 'company' => pn_m($id, 'company'), 'city' => pn_m($id, 'city'),
            'lang' => pn_m($id, 'lang'), 'type' => pn_m($id, 'type'), 'salary' => pn_m($id, 'salary'), 'posted' => pn_m($id, 'posted'),
            'about' => implode("\n\n", pn_paragraphs($p->post_content)), 'source' => pn_m($id, 'source'), 'url' => pn_m($id, 'url'),
            '_t' => $p->post_date];
    }
    usort($L, function ($a, $b) { return strcmp(($b['posted'] ?: substr($b['_t'], 0, 10)) . $b['_t'], ($a['posted'] ?: substr($a['_t'], 0, 10)) . $a['_t']); });
    return array_map(function ($j) { unset($j['_t']); return $j; }, $L);
}

/* Partners for the /links/ carousel (shape of data/links.json "partners"); expired are left out. */
function pn_partners() {
    $today = pn_today();
    if (!pn_has_entries('pn_partner')) {
        $L = array_map(function ($x) { $x['img'] = pn_asset_img($x['img'] ?? ''); return $x; }, pn_theme_json('links.json')['partners'] ?? []);
    } else {
        $L = [];
        foreach (pn_entries('pn_partner', ['orderby' => ['menu_order' => 'ASC', 'date' => 'DESC']]) as $p) {
            $id = $p->ID;
            $L[] = ['id' => $p->post_name, 'name' => pn_m($id, 'name'), 'title' => pn_title($p), 'text' => pn_m($id, 'text'), 'cta' => pn_m($id, 'cta') ?: 'Подробнее',
                'url' => pn_m($id, 'url'), 'img' => pn_thumb($id) ?: PN_URI . '/assets/img/group.jpg', 'pos' => pn_m($id, 'pos'), 'until' => pn_m($id, 'until')];
        }
    }
    return array_values(array_filter($L, function ($x) use ($today) { return empty($x['until']) || $x['until'] >= $today; }));
}
