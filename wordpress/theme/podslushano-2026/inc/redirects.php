<?php
/** Old addresses → the sections of the new site (301), so links and Google lead somewhere useful
    instead of «Не найдено (404)». The list comes from the Search Console 404 report. */
if (!defined('ABSPATH')) exit;

/* Path pattern => target: a path on the site, or 'spravochnik' for the Справочник rubric.
   Checked in order, the first match wins. */
function pn_old_redirects() {
    return [
        '#^/widget/?$#' => '/live/',
        '#^/collaboration-for-business-netherlands/?$#' => '/business/',
        // Old province pages
        '#^/province-(?:directory-)?[a-z-]+/?$#' => '/provinces/',
        // Old practical pages → Справочник
        '#^/(?:anwb-roadsidea-ssistance-netherlands|buy-rent-car-netherlands|car-accident-netherlands|integration-nl|free-dutch-language-practice)/?$#' => 'spravochnik',
        '#^/transport-netherlands/?$#' => '/trains/',
        '#^/(?:impressive-places-netherlands|netherlands-hotspot|government-tour)/?$#' => '/allowalks/',
        '#^/true-stories-about-life-netherlands/?$#' => '/news/',
        // Old blog
        '#^/blog/\d{4}/\d{2}/\d{2}/live-content[^/]*/?$#' => '/live/',
        '#^/blog/2026/01/18/#' => '/guide/',  // педагог по программированию → КонтактGuide
        '#^/blog(?:/|$)#' => '/news/',
    ];
}

/* Target for a request path, or null when the path is not an old address. */
function pn_old_redirect_target($path) {
    $path = rawurldecode((string) $path);
    foreach (pn_old_redirects() as $re => $to) {
        if (preg_match($re, $path)) return $to;
    }
    return null;
}

add_action('template_redirect', function () {
    $to = pn_old_redirect_target(wp_parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH));
    if ($to === null) return;
    wp_safe_redirect($to === 'spravochnik' ? pn_spravochnik_url() : home_url($to), 301);
    exit;
}, 1);
