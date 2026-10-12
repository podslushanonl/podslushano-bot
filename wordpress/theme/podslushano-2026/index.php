<?php
/** All front-end views render the same app shell; PHP passes the route and live data. */
if (!defined('ABSPATH')) exit;
$pn = ['route' => 'home', 'bot' => PN_BOT, 'ajax' => admin_url('admin-ajax.php'), 'nonce' => wp_create_nonce('pn_form')];
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
} elseif (is_page() || (is_singular() && !is_attachment())) {
    $p = get_queried_object();
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8'), 'html' => apply_filters('the_content', $p->post_content)];
} elseif (is_category() || is_tag() || is_search() || is_archive()) {
    $pn['route'] = 'news';
} elseif (is_404()) {
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => 'Страница не найдена', 'html' => '<p>Такой страницы нет. Попробуйте поиск или вернитесь на главную.</p>'];
}
$pn['wx'] = pn_weather();
$pn['spec'] = pn_specialists();
$pn['posts'] = pn_posts('news');
$pn['arts'] = pn_posts('arts');
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
<?php include PN_DIR . '/shell.php'; ?>
<?php if (!empty($pn['post']['html'])): ?>
<noscript><article class="wrap"><h1><?php echo esc_html($pn['post']['h']); ?></h1><?php echo $pn['post']['html']; // already filtered by the_content ?></article></noscript>
<?php endif; ?>
<?php wp_footer(); ?>
</body>
</html>
