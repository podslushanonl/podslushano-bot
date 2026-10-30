<?php
/**
 * podslushano.nl 2026 theme.
 * The front end is one app (assets/app.js) with real URLs; WordPress provides
 * posts, pages, SEO and admin. Live data: Buienradar (weather), the bot API
 * (specialists, NS trains, payments through Mollie).
 */
if (!defined('ABSPATH')) exit;

define('PN_VER', '1.6.0');
define('PN_BOT', 'https://worker-production-ad76.up.railway.app');
define('PN_DIR', get_template_directory());
define('PN_URI', get_template_directory_uri());

require PN_DIR . '/inc/data.php';
require PN_DIR . '/inc/content.php';
require PN_DIR . '/inc/forms.php';
require PN_DIR . '/inc/importer.php';
require PN_DIR . '/inc/seo.php';
require PN_DIR . '/inc/cities.php';
require PN_DIR . '/inc/specialists.php';
require PN_DIR . '/inc/donations.php';

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
    add_rewrite_rule('^city/([a-z0-9-]+)/?$', 'index.php?pn_route=city&pn_key=$matches[1]', 'top');
    add_rewrite_rule('^guide/[a-z0-9-]*?-?([0-9]+)/?$', 'index.php?pn_route=spec&pn_key=$matches[1]', 'top');
}
add_action('init', 'pn_add_rules');
// New sections need fresh rewrite rules: flush once whenever the route list changes.
add_action('init', function () {
    $ver = md5(wp_json_encode(pn_routes()) . 'city,spec');
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
        'city' => ['Город', 'Русскоязычные в городах Нидерландов: специалисты, события, новости.'],
        'spec' => ['КонтактGuide', 'Русскоязычный специалист в Нидерландах.'],
        'live' => ['Погода и камеры онлайн', 'Погода Buienradar по городам Нидерландов, дождь на 2 часа и живые камеры.'],
        'save' => ['Сэкономить: медстраховка 2027', 'Как выбрать медстраховку на 2027 год и не переплатить: eigen risico, типы полиса, zorgtoeslag. По-русски.'],
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
    if ($r === 'city' && ($c = pn_city(get_query_var('pn_key')))) return pn_city_title($c) . ' · podslushano.nl';
    if ($r === 'spec' && ($x = pn_spec(get_query_var('pn_key')))) return pn_spec_title($x) . ' · КонтактGuide';
    return $m[0] . ' · podslushano.nl';
}
function pn_route_desc() {
    $r = get_query_var('pn_route');
    if ($r === 'city' && ($c = pn_city(get_query_var('pn_key')))) return pn_city_desc($c);
    if ($r === 'spec' && ($x = pn_spec(get_query_var('pn_key')))) return pn_spec_desc($x);
    if ($r === 'event' && ($e = pn_event(get_query_var('pn_key')))) {
        // Each event gets its own description: date, place and what it is
        $where = implode(', ', array_filter([$e['venue'] ?? '', $e['city'] ?? '']));
        $about = ($e['s'] ?? '') ?: implode(' ', array_slice((array) ($e['p'] ?? []), 0, 1));
        $d = trim($e['h'] . ': ' . date_i18n('j F Y', strtotime($e['date'])) . ($where ? ', ' . $where : '') . '. ' . $about);
        return wp_trim_words($d, 28, '…');
    }
    return $r && ($m = pn_route_meta($r)) ? $m[1] : null;
}
function pn_route_url() {
    $r = get_query_var('pn_route');
    if (!$r) return null;
    if ($r === 'event') return home_url('/events/' . sanitize_key(get_query_var('pn_key')) . '/');
    if ($r === 'city') return home_url('/city/' . sanitize_key(get_query_var('pn_key')) . '/');
    if ($r === 'spec') return ($x = pn_spec(get_query_var('pn_key'))) ? pn_spec_url($x) : null;
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
// Home page: who we are, in the words people search with («русскоязычные в Нидерландах», «русскоязычное сообщество»)
define('PN_HOME_TITLE', 'podslushano.nl — русскоязычное сообщество в Нидерландах');
define('PN_HOME_DESC', 'podslushano.nl — русскоязычное сообщество в Нидерландах: новости на русском, русскоязычные специалисты, пошаговые справки про BSN, DigiD и налоги, афиша и прогулки.');
foreach (['wpseo_title', 'wpseo_opengraph_title', 'wpseo_twitter_title'] as $f) {
    add_filter($f, function ($t) { return is_front_page() && !get_query_var('pn_route') ? PN_HOME_TITLE : $t; }, 20);
}
foreach (['wpseo_metadesc', 'wpseo_opengraph_desc', 'wpseo_twitter_description'] as $f) {
    add_filter($f, function ($d) { return is_front_page() && !get_query_var('pn_route') ? PN_HOME_DESC : $d; }, 20);
}
// Organization in Yoast schema: what the community is and where, for search engines and assistants
add_filter('wpseo_schema_organization', function ($data) {
    $data['description'] = 'Русскоязычное сообщество и медиа в Нидерландах: новости, специалисты, справки, афиша.';
    $data['areaServed'] = ['@type' => 'Country', 'name' => 'Netherlands'];
    $data['knowsLanguage'] = ['ru', 'nl'];
    return $data;
});

/* /llms.txt: a plain description of the site for AI assistants. Yoast's own llms.txt must be off
   (Yoast SEO → Настройки → Функции сайта → llms.txt), otherwise its file is served instead. */
add_action('init', function () {
    if (rtrim((string) wp_parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/') !== '/llms.txt') return;
    $u = function ($p) { return home_url($p); };
    $out = "# podslushano.nl\n\n> " . PN_HOME_DESC . "\n\n"
        . "podslushano.nl — медиа и сообщество для русскоязычных жителей Нидерландов. Новости Нидерландов публикуются на русском каждый день, "
        . "практические справки обновляются по официальным источникам (rijksoverheid.nl, belastingdienst.nl, ind.nl и др.).\n\n## Разделы\n"
        . "- [Новости Нидерландов на русском](" . $u('/news/') . ")\n"
        . "- [Справочник: пошаговые инструкции](" . pn_spravochnik_url() . "): BSN, DigiD, налоги, пособия, жильё, работа\n"
        . "- [КонтактGuide](" . $u('/guide/') . "): русскоязычные специалисты в Нидерландах — врачи, юристы, бухгалтеры, мастера\n"
        . "- [Афиша](" . $u('/events/') . "): концерты, стендап, фестивали\n"
        . "- [Работа и жильё](" . $u('/work/') . ")\n- [Поезда NS](" . $u('/trains/') . ")\n- [Погода и камеры](" . $u('/live/') . ")\n"
        . "- [Сэкономить](" . $u('/save/') . ")\n- [Провинции Нидерландов](" . $u('/provinces/') . ")\n"
        . "- [allowalks: прогулки](" . $u('/allowalks/') . ")\n- [Магазин](" . $u('/shop/') . ")\n- [Связаться](" . $u('/contact/') . ")\n";
    $c = get_term_by('name', 'Справочник', 'category');
    if ($c) {
        $out .= "\n## Справки\n";
        foreach (get_posts(['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => 50, 'cat' => $c->term_id, 'no_found_rows' => true]) as $p) {
            $out .= '- [' . html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8') . '](' . get_permalink($p) . ")\n";
        }
    }
    $out .= "\n## Optional\n- [Карта сайта](" . $u('/sitemap_index.xml') . ")\n";
    header('Content-Type: text/plain; charset=UTF-8');
    header('X-Robots-Tag: noindex');
    echo $out;
    exit;
}, 1);

// App pages in the Yoast sitemap: /pn-pages-sitemap.xml
add_action('init', function () {
    global $wpseo_sitemaps;
    if (empty($wpseo_sitemaps) || !method_exists($wpseo_sitemaps, 'register_sitemap')) return;
    $wpseo_sitemaps->register_sitemap('pn-pages', function () {
        global $wpseo_sitemaps;
        $urls = array_map(function ($slug) { return home_url('/' . $slug . '/'); }, array_keys(pn_routes()));
        foreach (pn_events() as $e) if (!empty($e['key'])) $urls[] = home_url('/events/' . $e['key'] . '/');
        foreach (array_keys(pn_cities()) as $slug) $urls[] = home_url('/city/' . $slug . '/');
        foreach ((array) (pn_specialists() ?: []) as $x) if (!empty($x['id']) && !empty($x['name'])) $urls[] = pn_spec_url($x);
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
    echo '<meta name="theme-color" content="#F4F5F7" media="(prefers-color-scheme: light)">' . "\n";
    echo '<meta name="theme-color" content="#0E1014" media="(prefers-color-scheme: dark)">' . "\n";
}, 1);

// Yoast leaves the description empty when a post has no excerpt: use the lead of the article
add_filter('wpseo_metadesc', function ($d) {
    if ($d || !is_singular('post')) return $d;
    return wp_trim_words(wp_strip_all_tags(get_the_excerpt(get_queried_object())), 30, '…');
});

/* Cache Enabler stores pages in wp-content/cache; create the folder when it is missing. */
add_action('init', function () {
    if (!is_dir(WP_CONTENT_DIR . '/cache') && !get_transient('pn_mk_cache')) {
        set_transient('pn_mk_cache', 1, DAY_IN_SECONDS);
        wp_mkdir_p(WP_CONTENT_DIR . '/cache');
    }
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


/* ---------- The bot asks the site to refresh: after an afisha change or a change in КонтактGuide ----------
   POST /wp-json/pn/v1/refresh with the bot's application password: forget the cached bot feed and clear the page cache. */
add_action('rest_api_init', function () {
    register_rest_route('pn/v1', '/refresh', [
        'methods' => 'POST',
        'permission_callback' => function () { return current_user_can('edit_posts'); },
        'callback' => function () {
            delete_transient('pn_user_ev2');
            delete_transient('pn_spec');   // КонтактGuide: новая или изменённая карточка
            do_action('cache_enabler_clear_complete_cache');
            return ['ok' => true];
        },
    ]);
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
