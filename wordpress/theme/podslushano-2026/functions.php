<?php
/**
 * podslushano.nl 2026 theme.
 * The front end is one app (assets/app.js) with real URLs; WordPress provides
 * posts, pages, SEO and admin. Live data: Buienradar (weather), the bot API
 * (specialists, NS trains, payments through Mollie).
 */
if (!defined('ABSPATH')) exit;

define('PN_VER', '1.3.0');
define('PN_BOT', 'https://worker-production-ad76.up.railway.app');
define('PN_DIR', get_template_directory());
define('PN_URI', get_template_directory_uri());

require PN_DIR . '/inc/data.php';
require PN_DIR . '/inc/content.php';
require PN_DIR . '/inc/forms.php';
require PN_DIR . '/inc/importer.php';
require PN_DIR . '/inc/seo.php';

add_action('after_setup_theme', function () {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('html5', ['search-form', 'gallery', 'caption', 'style', 'script']);
});

/* ---------- app routes with pretty URLs ---------- */
function pn_routes() {
    return [
        'news' => 'news', 'guide' => 'guide', 'events' => 'events', 'live' => 'live',
        'allowalks' => 'allo', 'shop' => 'shop', 'trains' => 'trains', 'provinces' => 'provinces',
        'work' => 'board', 'place' => 'place', 'cabinet' => 'cabinet', 'business' => 'business',
        'contact' => 'contact', 'travel' => 'travel', 'save' => 'save',
    ];
}
function pn_add_rules() {
    foreach (pn_routes() as $slug => $route) {
        add_rewrite_rule('^' . $slug . '/?$', 'index.php?pn_route=' . $route, 'top');
    }
    add_rewrite_rule('^events/([a-z0-9-]+)/?$', 'index.php?pn_route=event&pn_key=$matches[1]', 'top');
}
add_action('init', 'pn_add_rules');
// New sections need fresh rewrite rules: flush once whenever the route list changes.
add_action('init', function () {
    $ver = md5(wp_json_encode(pn_routes()));
    if (get_option('pn_rules_ver') !== $ver) {
        flush_rewrite_rules(false);
        update_option('pn_rules_ver', $ver);
    }
}, 99);
add_filter('query_vars', function ($v) { $v[] = 'pn_route'; $v[] = 'pn_key'; return $v; });
add_action('after_switch_theme', function () { pn_add_rules(); flush_rewrite_rules(); });
add_filter('redirect_canonical', function ($url) { return get_query_var('pn_route') ? false : $url; });
// Old addresses: the phone widget page was removed, the old business page is replaced by /business/.
add_action('template_redirect', function () {
    $path = (string) wp_parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);
    foreach (['#^/widget/?$#' => '/live/', '#^/collaboration-for-business-netherlands/?$#' => '/business/'] as $re => $to) {
        if (preg_match($re, $path)) {
            wp_safe_redirect(home_url($to), 301);
            exit;
        }
    }
}, 1);
add_filter('template_include', function ($t) {
    return get_query_var('pn_route') ? PN_DIR . '/index.php' : $t;
});

/* ---------- titles and descriptions for app routes ---------- */
function pn_route_meta($route) {
    $m = [
        'news' => ['Новости Нидерландов на русском', 'Главные новости Нидерландов на русском языке: транспорт, жильё, деньги, погода. Без политики.'],
        'guide' => ['КонтактGuide: русскоязычные специалисты', 'Русскоязычные специалисты в Нидерландах: врачи, юристы, бухгалтеры, мастера. Поиск по провинции и категории.'],
        'events' => ['Афиша: концерты, стендап, фестивали', 'Концерты, стендап, театр и фестивали в Нидерландах для русскоязычных.'],
        'event' => ['Афиша', 'Событие в Нидерландах: дата, место, билеты.'],
        'live' => ['Погода и камеры онлайн', 'Погода Buienradar по городам Нидерландов, дождь на 2 часа и живые камеры.'],
        'save' => ['Сэкономить: медстраховка 2027 и eSIM', 'Как выбрать медстраховку на 2027 год и не переплатить, eigen risico, типы полиса, eSIM для поездок. По-русски.'],
        'trains' => ['Поезда NS: табло, отмены и сбои', 'Табло отправлений NS по станциям, отмены, сбои и ремонтные работы на железной дороге Нидерландов на русском.'],
        'allo' => ['allowalks: прогулки по Нидерландам', 'Прогулки allowalks в небольшой компании и подарочные карты.'],
        'shop' => ['Магазин', 'Подарочные карты allowalks, размещение в КонтактGuide, гайды и стикеры.'],
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
function pn_route_title() {
    $r = get_query_var('pn_route');
    if (!$r || !($m = pn_route_meta($r))) return null;
    if ($r === 'event' && ($e = pn_event(get_query_var('pn_key')))) return $e['h'] . ' · Афиша podslushano.nl';
    return $m[0] . ' · podslushano.nl';
}
function pn_route_desc() {
    $r = get_query_var('pn_route');
    return $r && ($m = pn_route_meta($r)) ? $m[1] : null;
}
function pn_route_url() {
    $r = get_query_var('pn_route');
    if (!$r) return null;
    if ($r === 'event') return home_url('/events/' . sanitize_key(get_query_var('pn_key')) . '/');
    $slug = array_search($r, pn_routes(), true);
    return $slug ? home_url('/' . $slug . '/') : null;
}
add_filter('pre_get_document_title', function ($t) { return pn_route_title() ?? $t; });

/* ---------- Yoast SEO: app routes are virtual, give Yoast their own title, description and URL ---------- */
foreach (['wpseo_title', 'wpseo_opengraph_title', 'wpseo_twitter_title'] as $f) {
    add_filter($f, function ($t) { return pn_route_title() ?? $t; });
}
foreach (['wpseo_metadesc', 'wpseo_opengraph_desc', 'wpseo_twitter_description'] as $f) {
    add_filter($f, function ($d) { return pn_route_desc() ?? $d; });
}
foreach (['wpseo_canonical', 'wpseo_opengraph_url'] as $f) {
    add_filter($f, function ($u) { return pn_route_url() ?? $u; });
}
// App pages in the Yoast sitemap: /pn-pages-sitemap.xml
add_action('init', function () {
    global $wpseo_sitemaps;
    if (empty($wpseo_sitemaps) || !method_exists($wpseo_sitemaps, 'register_sitemap')) return;
    $wpseo_sitemaps->register_sitemap('pn-pages', function () {
        global $wpseo_sitemaps;
        $urls = array_map(function ($slug) { return home_url('/' . $slug . '/'); }, array_keys(pn_routes()));
        foreach (pn_events() as $e) if (!empty($e['key'])) $urls[] = home_url('/events/' . $e['key'] . '/');
        $xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">';
        foreach ($urls as $u) $xml .= '<url><loc>' . esc_url($u) . '</loc></url>';
        $wpseo_sitemaps->set_sitemap($xml . '</urlset>');
    });
}, 20);
add_filter('wpseo_sitemap_index', function ($x) {
    return $x . '<sitemap><loc>' . esc_url(home_url('/pn-pages-sitemap.xml')) . '</loc></sitemap>';
});

/* ---------- Complianz: when active, its banner and consent replace the theme's own ---------- */
function pn_complianz() {
    return defined('cmplz_version') || class_exists('COMPLIANZ');
}
// The app data and /links/ scripts mention Instagram and YouTube links; Complianz must not block them as embeds.
add_filter('wp_inline_script_attributes', function ($attr) {
    if (($attr['id'] ?? '') === 'pn-app-js-before') $attr['data-category'] = 'functional';
    return $attr;
});
add_filter('cmplz_whitelisted_script_tags', function ($tags) {
    $tags[] = 'window.PN=';
    $tags[] = 'window.PNL=';
    $tags[] = 'pn-links-app';
    return $tags;
});

/* ---------- Plausible on /links/ (that page is standalone and skips wp_head) ---------- */
function pn_analytics_tags() {
    ob_start();
    wp_head();
    $head = ob_get_clean();
    preg_match_all('#<script\b[^>]*>.*?</script>#is', $head, $m);
    return implode("\n", array_filter($m[0], function ($tag) { return stripos($tag, 'plausible') !== false; })) . "\n";
}
add_action('wp_head', function () {
    $r = get_query_var('pn_route');
    $d = '';
    if ($r && ($m = pn_route_meta($r))) $d = $m[1];
    elseif (is_front_page() || is_home()) $d = 'podslushano.nl: Нидерланды изнутри. Новости, русскоязычные специалисты, афиша, погода и прогулки.';
    elseif (is_singular()) $d = wp_trim_words(get_the_excerpt(), 30, '…');
    if ($d && !defined('WPSEO_VERSION') && !defined('RANK_MATH_VERSION')) {
        echo '<meta name="description" content="' . esc_attr($d) . '">' . "\n";
    }
    echo '<meta name="theme-color" content="#F4F5F7">' . "\n";
    // Подтверждение сайта для партнёрской сети Impact (eSIM)
    echo "<meta name='impact-site-verification' value='42876f45-152c-4874-81ce-e154db4b471f'>" . "\n";
}, 1);

// Yoast leaves the description empty when a post has no excerpt: use the lead of the article
add_filter('wpseo_metadesc', function ($d) {
    if ($d || !is_singular('post')) return $d;
    return wp_trim_words(wp_strip_all_tags(get_the_excerpt(get_queried_object())), 30, '…');
});

/* ---------- assets ---------- */
add_action('wp_enqueue_scripts', function () {
    if (is_page('links')) return;
    wp_enqueue_style('pn-app', PN_URI . '/assets/app.css', [], PN_VER . '.' . @filemtime(PN_DIR . '/assets/app.css'));
    wp_enqueue_script('pn-app', PN_URI . '/assets/app.js', [], PN_VER . '.' . @filemtime(PN_DIR . '/assets/app.js'), true);
    wp_dequeue_style('wp-block-library');
    wp_dequeue_style('global-styles');
    wp_dequeue_style('classic-theme-styles');
}, 20);
remove_action('wp_head', 'print_emoji_detection_script', 7);
remove_action('wp_print_styles', 'print_emoji_styles');

/* The site logo is only used inside the (usually hidden) Complianz banner: load a small
   size and only when the banner is actually shown, instead of a 1024px PNG on every page. */
add_filter('get_custom_logo_image_attributes', function ($attr) {
    $attr['sizes'] = '96px';
    $attr['loading'] = 'lazy';
    unset($attr['fetchpriority']);
    return $attr;
});


/* ---------- Mobile app (podslushano): one public JSON with the live content ---------- */
add_action('rest_api_init', function () {
    register_rest_route('pn/v1', '/app', [
        'methods' => 'GET',
        'permission_callback' => '__return_true',
        'callback' => function () {
            $events = array_map(function ($e) {
                return array_intersect_key($e, array_flip(['key', 'h', 's', 'date', 'time', 'end', 'venue', 'addr', 'city', 'price', 'img', 'url', 'cat', 'p', 'tickets', 'partner']));
            }, array_slice(pn_events(), 0, 60));
            $jobs = array_map(function ($j) {
                return array_intersect_key($j, array_flip(['id', 'title', 'company', 'city', 'lang', 'type', 'salary', 'posted', 'about', 'url']));
            }, array_slice(pn_jobs(), 0, 40));
            $resp = new WP_REST_Response([
                'v' => 1,
                'news' => pn_posts('news', 30),
                'events' => $events,
                'jobs' => $jobs,
                'wx' => pn_weather(),
                'bot' => PN_BOT,
            ]);
            $resp->header('Cache-Control', 'public, max-age=120');
            return $resp;
        },
    ]);
});
