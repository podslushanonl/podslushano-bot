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
    $html = preg_replace('#(<section class="page( on)?" id="p-home"[^>]*>)#', '$1<h1 class="sr">podslushano.nl: Нидерланды изнутри — новости, специалисты, афиша</h1>', $html, 1);
    if ($route === 'art' && !empty($pn['post'])) $html = pn_seo_fill($html, 'artBody', pn_seo_art($pn['post']));
    if ($route === 'wp' && !empty($pn['page'])) {
        $html = pn_seo_fill($html, 'wpBody', pn_seo_back('/', 'Главная') . '<h1>' . esc_html($pn['page']['title']) . '</h1>' . $pn['page']['html']);
    }
    if ($route === 'event' && ($e = pn_event($pn['param'] ?? ''))) $html = pn_seo_fill($html, 'evDet', pn_seo_event($e));
    if ($route === 'news') $html = pn_seo_fill($html, 'newsBody', pn_seo_news_list(array_merge($pn['posts'], pn_posts('arts'))));
    if ($route === 'home') $html = pn_seo_fill($html, 'homeNews', pn_seo_news_list(array_slice($pn['posts'], 0, 8)));
    // "#route" links → real addresses (JS keeps them fast: it catches the click and switches the section)
    $map = ['home' => '/', 'links' => '/links/'];
    foreach (pn_routes() as $slug => $r) $map[$r] = '/' . $slug . '/';
    return preg_replace_callback('#href="\#([a-z0-9-]+)"#', function ($m) use ($map) {
        if (!isset($map[$m[1]])) return $m[0];
        return 'href="' . esc_url(home_url($map[$m[1]])) . '" data-hash="' . $m[1] . '"';
    }, $html);
}
