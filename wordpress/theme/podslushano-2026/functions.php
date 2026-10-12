<?php
/**
 * podslushano.nl 2026 theme.
 * The front end is one app (assets/app.js) with real URLs; WordPress provides
 * posts, pages, SEO and admin. Live data: Buienradar (weather), the bot API
 * (specialists, NS trains, payments through Mollie).
 */
if (!defined('ABSPATH')) exit;

define('PN_VER', '1.0.0');
define('PN_BOT', 'https://worker-production-ad76.up.railway.app');
define('PN_DIR', get_template_directory());
define('PN_URI', get_template_directory_uri());

require PN_DIR . '/inc/data.php';
require PN_DIR . '/inc/forms.php';
require PN_DIR . '/inc/importer.php';

add_action('after_setup_theme', function () {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('html5', ['search-form', 'gallery', 'caption', 'style', 'script']);
});

/* ---------- app routes with pretty URLs ---------- */
function pn_routes() {
    return [
        'news' => 'news', 'guide' => 'guide', 'events' => 'events', 'live' => 'live',
        'allowalks' => 'allo', 'shop' => 'shop', 'widget' => 'widget', 'provinces' => 'provinces',
        'work' => 'board', 'place' => 'place', 'cabinet' => 'cabinet', 'business' => 'business',
        'contact' => 'contact', 'travel' => 'travel',
    ];
}
function pn_add_rules() {
    foreach (pn_routes() as $slug => $route) {
        add_rewrite_rule('^' . $slug . '/?$', 'index.php?pn_route=' . $route, 'top');
    }
    add_rewrite_rule('^events/([a-z0-9-]+)/?$', 'index.php?pn_route=event&pn_key=$matches[1]', 'top');
}
add_action('init', 'pn_add_rules');
add_filter('query_vars', function ($v) { $v[] = 'pn_route'; $v[] = 'pn_key'; return $v; });
add_action('after_switch_theme', function () { pn_add_rules(); flush_rewrite_rules(); });
add_filter('redirect_canonical', function ($url) { return get_query_var('pn_route') ? false : $url; });
add_filter('template_include', function ($t) {
    return get_query_var('pn_route') ? PN_DIR . '/index.php' : $t;
});

/* ---------- titles and descriptions for app routes ---------- */
function pn_route_meta($route) {
    $m = [
        'news' => ['Новости Нидерландов на русском', 'Главные новости Нидерландов по-русски: транспорт, жильё, деньги, погода. Без политики.'],
        'guide' => ['КонтактGuide: русскоязычные специалисты', 'Русскоязычные специалисты в Нидерландах: врачи, юристы, бухгалтеры, мастера. Поиск по провинции и категории.'],
        'events' => ['Афиша: концерты, стендап, фестивали', 'Концерты, стендап, театр и фестивали в Нидерландах для русскоязычных.'],
        'event' => ['Афиша', 'Событие в Нидерландах: дата, место, билеты.'],
        'live' => ['Погода и камеры онлайн', 'Погода Buienradar по городам Нидерландов, дождь на 2 часа и живые камеры.'],
        'allo' => ['allowalks: прогулки по Нидерландам', 'Прогулки allowalks в небольшой компании и подарочные карты.'],
        'shop' => ['Магазин', 'Подарочные карты allowalks, размещение в КонтактGuide, гайды и стикеры.'],
        'widget' => ['Виджет на телефон', 'Погода, дождь, поезда NS и главное дня на экране телефона.'],
        'provinces' => ['Провинции Нидерландов', 'История и особенности двенадцати провинций Нидерландов.'],
        'board' => ['Работа и жильё', 'Вакансии с русским и украинским языком и проверенные площадки для поиска жилья.'],
        'place' => ['Разместить карточку в КонтактGuide', 'Разместите карточку специалиста на сайте и в боте podslushano.nl.'],
        'cabinet' => ['Кабинет бизнеса', 'Управление карточкой в КонтактGuide.'],
        'business' => ['Сотрудничество и реклама', 'Форматы рекламы и сотрудничества с podslushano.nl.'],
        'contact' => ['Связаться с нами', 'Напишите редакции podslushano.nl.'],
        'travel' => ['Путешествия', 'Билеты и идеи для поездок из Нидерландов.'],
    ];
    return $m[$route] ?? null;
}
add_filter('pre_get_document_title', function ($t) {
    $r = get_query_var('pn_route');
    if ($r && ($m = pn_route_meta($r))) {
        if ($r === 'event' && ($e = pn_event(get_query_var('pn_key')))) return $e['h'] . ' · Афиша podslushano.nl';
        return $m[0] . ' · podslushano.nl';
    }
    return $t;
});
add_action('wp_head', function () {
    $r = get_query_var('pn_route');
    $d = '';
    if ($r && ($m = pn_route_meta($r))) $d = $m[1];
    elseif (is_front_page() || is_home()) $d = 'podslushano.nl: всё о жизни в Нидерландах по-русски. Новости, специалисты, афиша, погода и прогулки.';
    elseif (is_singular()) $d = wp_trim_words(get_the_excerpt(), 30, '…');
    if ($d && !defined('WPSEO_VERSION') && !defined('RANK_MATH_VERSION')) {
        echo '<meta name="description" content="' . esc_attr($d) . '">' . "\n";
    }
    echo '<meta name="theme-color" content="#F4F5F7">' . "\n";
}, 1);

/* ---------- assets ---------- */
add_action('wp_enqueue_scripts', function () {
    if (is_page('links')) return;
    wp_enqueue_style('pn-app', PN_URI . '/assets/app.css', [], PN_VER);
    wp_enqueue_script('pn-app', PN_URI . '/assets/app.js', [], PN_VER, true);
    wp_dequeue_style('wp-block-library');
    wp_dequeue_style('global-styles');
    wp_dequeue_style('classic-theme-styles');
}, 20);
remove_action('wp_head', 'print_emoji_detection_script', 7);
remove_action('wp_print_styles', 'print_emoji_styles');
