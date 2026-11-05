<?php
/** pn_cached never makes a visitor wait for a slow source: php wordpress/tests/cache.php */
define('ABSPATH', __DIR__);
define('MINUTE_IN_SECONDS', 60);
define('PN_BOT', 'https://bot.example');
$transients = []; $options = []; $scheduled = []; $actions = []; $fetches = 0;
function get_transient($k) { return $GLOBALS['transients'][$k] ?? false; }
function set_transient($k, $v, $ttl) { $GLOBALS['transients'][$k] = $v; }
function get_option($k, $d = false) { return $GLOBALS['options'][$k] ?? $d; }
function update_option($k, $v, ...$a) { $GLOBALS['options'][$k] = $v; }
function wp_next_scheduled($hook, $args) { return isset($GLOBALS['scheduled'][$hook . json_encode($args)]) ? time() : false; }
function wp_schedule_single_event($t, $hook, $args) { $GLOBALS['scheduled'][$hook . json_encode($args)] = $args; return true; }
function add_action($hook, $fn, ...$a) { $GLOBALS['actions'][$hook] = $fn; }
function add_filter(...$a) {}
require dirname(__DIR__) . '/theme/podslushano-2026/inc/data.php';

function pn_test_source() { $GLOBALS['fetches']++; return ['fresh' => $GLOBALS['fetches']]; }
function pn_test_broken() { $GLOBALS['fetches']++; return null; }

$fail = 0;
function check($ok, $what) { global $fail; echo ($ok ? 'ok   ' : 'FAIL ') . $what . "\n"; if (!$ok) $fail++; }

// 1. Nothing stored yet: the first load fetches inline and remembers the value.
$v = pn_cached('k', 600, 'pn_test_source');
check($v === ['fresh' => 1] && $fetches === 1, 'first load fetches inline');
check(get_option('k_last') === ['fresh' => 1], 'last good value remembered');

// 2. Fresh transient: no fetch at all.
$v = pn_cached('k', 600, 'pn_test_source');
check($v === ['fresh' => 1] && $fetches === 1, 'fresh value served from cache');

// 3. Expired: the visitor gets the last value at once, no inline fetch, refresh is scheduled once.
unset($transients['k']);
$v = pn_cached('k', 600, 'pn_test_source');
check($v === ['fresh' => 1] && $fetches === 1, 'expired value served without waiting for the source');
check(count($scheduled) === 1 && array_values($scheduled)[0] === ['k', 600, 'pn_test_source'], 'one background refresh scheduled');
unset($transients['k']);
pn_cached('k', 600, 'pn_test_source');
check(count($scheduled) === 1, 'no duplicate refresh while one is pending');

// 4. The background refresh (WP-Cron) fetches and stores the new value.
$actions['pn_cache_refresh']('k', 600, 'pn_test_source');
check($fetches === 2 && get_option('k_last') === ['fresh' => 2] && get_transient('k') === ['fresh' => 2], 'cron refresh stores new value');

// 5. A failing source never empties the site.
$actions['pn_cache_refresh']('k', 600, 'pn_test_broken');
check(get_option('k_last') === ['fresh' => 2], 'failed refresh keeps last good value');

// 6. The cron hook only calls theme functions.
$before = $fetches;
$actions['pn_cache_refresh']('k', 600, 'phpinfo');
check($fetches === $before && get_option('k_last') === ['fresh' => 2], 'cron hook ignores non-theme callables');

// 7. The real sources are named functions, so the background refresh can call them.
foreach (['pn_weather_fetch', 'pn_specialists_fetch', 'pn_bot_afisha_fetch'] as $fn) check(function_exists($fn), "$fn exists");

exit($fail ? 1 : 0);
