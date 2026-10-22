<?php
/* ---------- Specialist pages: /guide/<slug>-<id>/ ----------
 * Every card of КонтактGuide gets its own address, so a search like «русский стоматолог Amsterdam»
 * can lead straight to the specialist. Data comes from the bot (pn_specialists), the page is shown
 * as an ordinary page (route "wp"), with ProfessionalService markup for search engines. */
if (!defined('ABSPATH')) exit;

function pn_spec_url($x) {
    $slug = sanitize_title((string) ($x['slug'] ?? '')) ?: 'specialist';
    return home_url('/guide/' . $slug . '-' . (int) $x['id'] . '/');
}
function pn_spec($id) {
    foreach ((array) (pn_specialists() ?: []) as $x) if ((int) ($x['id'] ?? 0) === (int) $id && !empty($x['name'])) return $x;
    return null;
}
function pn_spec_where($x) {
    if (!empty($x['online']) && empty($x['city'])) return 'онлайн';
    return implode(', ', array_filter([$x['city'] ?? '', $x['province'] ?? '']));
}
function pn_spec_cat($x) {
    $c = trim((string) ($x['category'] ?? ''));
    return $c === '' ? '' : mb_strtoupper(mb_substr($c, 0, 1)) . mb_substr($c, 1);
}
function pn_spec_title($x) {
    $where = pn_spec_where($x);
    return $x['name'] . ' — ' . mb_strtolower(pn_spec_cat($x)) . ($where ? ', ' . $where : '');
}
function pn_spec_desc($x) {
    $d = wp_trim_words(wp_strip_all_tags((string) ($x['description'] ?? '')), 24, '…');
    return trim(pn_spec_cat($x) . ', говорит по-русски' . (pn_spec_where($x) ? ' · ' . pn_spec_where($x) : '') . '. ' . $d);
}

function pn_spec_page($x) {
    $where = pn_spec_where($x);
    $h = '<p class="lead">' . esc_html(pn_spec_cat($x)) . ($where ? ' · ' . esc_html($where) : '')
        . (!empty($x['online']) && !empty($x['city']) ? ' · работает и онлайн' : '') . '</p>';
    if (!empty($x['description'])) $h .= '<p>' . nl2br(esc_html(wp_strip_all_tags((string) $x['description']))) . '</p>';
    if (!empty($x['rating']) && !empty($x['reviews'])) {
        $h .= '<p><strong>' . esc_html(number_format((float) $x['rating'], 1, ',', '')) . ' из 5</strong> · отзывов: ' . (int) $x['reviews'] . '</p>';
    }
    // Contacts the specialist published in КонтактGuide
    $labels = ['instagram' => 'Instagram', 'telegram' => 'Telegram', 'website' => 'Сайт', 'email' => 'Почта', 'phone' => 'Телефон'];
    $links = '';
    foreach ((array) ($x['links'] ?? []) as $l) {
        $url = (string) ($l['url'] ?? '');
        if (!preg_match('#^(https://|mailto:|tel:)#', $url)) continue;
        $ext = strpos($url, 'https://') === 0 ? ' target="_blank" rel="noopener nofollow"' : '';
        $links .= '<a class="btn btn-soft btn-sm" href="' . esc_url($url, ['https', 'mailto', 'tel']) . '"' . $ext . '>' . esc_html($labels[$l['type'] ?? ''] ?? 'Связаться') . '</a> ';
    }
    if ($links) $h .= '<h2>Связаться</h2><p class="spec-links">' . $links . '</p><p>Скажите, что нашли контакт на podslushano.nl.</p>';

    // Others in the same category nearby: first the same province, then the rest
    $same = $other = [];
    foreach ((array) (pn_specialists() ?: []) as $y) {
        if ((int) ($y['id'] ?? 0) === (int) $x['id'] || empty($y['name']) || ($y['category'] ?? '') !== ($x['category'] ?? '')) continue;
        if (($y['province'] ?? '') === ($x['province'] ?? '')) $same[] = $y; else $other[] = $y;
    }
    $more = array_slice(array_merge($same, $other), 0, 6);
    if ($more) {
        $h .= '<h2>Ещё: ' . esc_html(mb_strtolower(pn_spec_cat($x))) . '</h2><ul class="pg-list">';
        foreach ($more as $y) {
            $h .= '<li><a href="' . esc_url(pn_spec_url($y)) . '">' . esc_html($y['name']) . '</a>' . (pn_spec_where($y) ? ' · ' . esc_html(pn_spec_where($y)) : '') . '</li>';
        }
        $h .= '</ul>';
    }
    // The city page, when the specialist's city has one
    foreach (pn_cities() as $slug => $c) {
        if (mb_strtolower($c[0]) === mb_strtolower(trim((string) ($x['city'] ?? '')))) {
            $h .= '<p><a href="' . esc_url(home_url('/city/' . $slug . '/')) . '">Русскоязычные в ' . esc_html($c[0]) . '</a></p>';
            break;
        }
    }
    $h .= '<p><a href="' . esc_url(home_url('/guide/')) . '">Все специалисты в КонтактGuide</a> · <a href="' . esc_url(home_url('/place/'))
        . '">Разместить свою карточку</a></p>';
    return $h;
}

/* schema.org ProfessionalService for the specialist page */
function pn_spec_ld($x) {
    $ld = ['@context' => 'https://schema.org', '@type' => 'ProfessionalService', 'name' => $x['name'], 'url' => pn_spec_url($x),
        'description' => wp_strip_all_tags((string) ($x['description'] ?? '')), 'knowsLanguage' => ['ru'],
        'areaServed' => !empty($x['online']) ? ['@type' => 'Country', 'name' => 'Netherlands'] : ($x['city'] ?: ($x['province'] ?? ''))];
    if (!empty($x['city']) || !empty($x['province'])) {
        $ld['address'] = array_filter(['@type' => 'PostalAddress', 'addressLocality' => $x['city'] ?? '', 'addressRegion' => $x['province'] ?? '', 'addressCountry' => 'NL']);
    }
    $same = [];
    foreach ((array) ($x['links'] ?? []) as $l) if (in_array($l['type'] ?? '', ['instagram', 'website', 'telegram'], true) && strpos((string) $l['url'], 'https://') === 0) $same[] = $l['url'];
    if ($same) $ld['sameAs'] = $same;
    if (!empty($x['photo']) && preg_match('#^https://#', (string) $x['photo'])) $ld['image'] = $x['photo'];
    if (!empty($x['rating']) && !empty($x['reviews'])) {
        $ld['aggregateRating'] = ['@type' => 'AggregateRating', 'ratingValue' => (float) $x['rating'], 'reviewCount' => (int) $x['reviews']];
    }
    return $ld;
}
add_action('wp_head', function () {
    if (get_query_var('pn_route') !== 'spec' || !($x = pn_spec(get_query_var('pn_key')))) return;
    echo '<script type="application/ld+json">' . wp_json_encode(pn_spec_ld($x), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG) . '</script>' . "\n";
}, 5);
