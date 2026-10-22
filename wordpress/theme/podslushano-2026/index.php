<?php
/** All front-end views render the same app shell; PHP passes the route and live data. */
if (!defined('ABSPATH')) exit;
$pn = ['route' => 'home', 'bot' => PN_BOT, 'ajax' => admin_url('admin-ajax.php'), 'cmp' => pn_complianz()];
$r = get_query_var('pn_route');
if ($r) {
    $pn['route'] = $r;
    if ($r === 'event') {
        $pn['param'] = sanitize_key(get_query_var('pn_key'));
        if (!pn_event($pn['param'])) status_header(404);
    }
} elseif (is_singular('post')) {
    $pn['route'] = 'art';
    $pn['post'] = pn_post_item(get_queried_object(), true);
    // One native hint inside the text: the section of the site on the same topic (КонтактGuide, афиша, Справочник…)
    $pn['post']['html'] = pn_native_insert($pn['post']['html'], $pn['post']['cat'], $pn['post']['h']);
} elseif (is_page() || (is_singular() && !is_attachment())) {
    $p = get_queried_object();
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8'), 'html' => apply_filters('the_content', $p->post_content)];
} elseif (is_category() || is_tag() || is_search() || is_archive()) {
    $pn['route'] = 'news';
    // Category / tag page: its own posts and heading (Справочник, Транспорт…), not the general feed
    if ((is_category() || is_tag()) && ($term = get_queried_object())) {
        $pn['term'] = ['name' => $term->name, 'desc' => wp_strip_all_tags(term_description($term))];
        $pn['termPosts'] = array_map('pn_post_item', get_posts(['post_type' => 'post', 'post_status' => 'publish', 'posts_per_page' => 60,
            'no_found_rows' => true, 'ignore_sticky_posts' => true, 'tax_query' => [['taxonomy' => $term->taxonomy, 'terms' => $term->term_id]]]));
    }
} elseif (is_404()) {
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => 'Страница не найдена', 'html' => '<p>Такой страницы нет. Попробуйте поиск или вернитесь на главную.</p>'];
}
// App pages carry live weather and specialists: keep them out of Cache Enabler. Posts and pages stay cached.
if (!in_array($pn['route'], ['art', 'wp'], true) && !defined('DONOTCACHEPAGE')) define('DONOTCACHEPAGE', true);
$pn['wx'] = pn_weather();
$pn['spec'] = pn_specialists();
$pn['posts'] = !empty($pn['termPosts']) ? $pn['termPosts'] : pn_posts('news');
unset($pn['termPosts']);
$pn['arts'] = pn_posts('arts');
// Афиша and Вакансии from wp-admin (theme JSON while empty), upcoming only
$pn['events'] = pn_events();
$pn['past'] = pn_past_events();
$pn['jobs'] = pn_jobs();
add_action('wp_enqueue_scripts', function () use ($pn) {
    wp_add_inline_script('pn-app', 'window.PN=' . wp_json_encode($pn) . ';', 'before');
}, 30);
?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo('charset'); ?>">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<?php
// Search engines get the current section with its text and real links (inc/seo.php)
ob_start();
include PN_DIR . '/shell.php';
echo pn_seo_shell(ob_get_clean(), $pn);
?>
<?php wp_footer(); ?>
</body>
</html>
