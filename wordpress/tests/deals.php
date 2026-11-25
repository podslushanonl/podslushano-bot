<?php
// Pure function smoke test; no WordPress server, no Mollie keys or network requests.
define('ABSPATH', __DIR__);
function add_action(...$args) {}
function add_shortcode(...$args) {}
require __DIR__.'/../theme/podslushano-2026/inc/deals.php';
function pd_check($actual,$expected) {
    if ($actual!==$expected) { fwrite(STDERR,var_export([$actual,$expected],true).PHP_EOL); exit(1); }
}
pd_check(pn_deals_plan('month')['cents'],399);
pd_check(pn_deals_plan('month')['interval'],'1 month');
pd_check(pn_deals_plan('year')['cents'],3999);
pd_check(pn_deals_plan('year')['months'],12);
pd_check(pn_deals_plan('year')['interval'],null);
pd_check(pn_deals_plan('unknown'),null);
pd_check(pn_deals_plan(['month']),null);
pd_check(pn_deals_period_end('2026-01-31T12:00:00Z',1),'2026-02-28');
pd_check(pn_deals_period_end('2024-02-29T12:00:00Z',12),'2025-02-28');
pd_check(pn_deals_period_end('2026-11-25T12:00:00Z',12),'2027-11-25');
pd_check(pn_deals_period_end('bad',12),'');
echo "Vygodno NL plan/date checks passed\n";
