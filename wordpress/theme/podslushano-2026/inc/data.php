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
    foreach (['stati', 'statyi', 'articles', 'stati-ru'] as $slug) {
        $c = get_category_by_slug($slug);
        if ($c) $ids[] = $c->term_id;
    }
    $c = get_term_by('name', 'Статьи', 'category');
    if ($c) $ids[] = $c->term_id;
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

/* ---------- events (bundled data, used for titles) ---------- */
function pn_events() {
    static $ev = null;
    if ($ev === null) {
        $j = json_decode((string) @file_get_contents(PN_DIR . '/data/events.json'), true);
        $ev = is_array($j) ? $j : [];
    }
    return $ev;
}
function pn_event($key) {
    foreach (pn_events() as $e) if (($e['key'] ?? '') === $key) return $e;
    return null;
}
