// Разбор статьи справочника (HTML с классами pg-*, их собирает utils/site_guides.py) в блоки для нативного показа.

export type Block =
  | { t: 'meta'; text: string }
  | { t: 'sum'; rows: [string, string][] }
  | { t: 'h2' | 'h3' | 'p'; text: string }
  | { t: 'list' | 'check'; items: string[] }
  | { t: 'steps'; items: { title: string; text: string }[] }
  | { t: 'note'; kind: 'tip' | 'warn' | 'info'; title: string; text: string[] }
  | { t: 'table'; head: string[]; rows: string[][] }
  | { t: 'faq'; items: { q: string; a: string }[] }
  | { t: 'cta' }
  | { t: 'src'; links: { title: string; url: string }[] };

const txt = (s: string) => s
  .replace(/<br\s*\/?>/g, '\n').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&#8230;|&hellip;/g, '…')
  .replace(/&#8211;|&ndash;/g, '–').replace(/&#8212;|&mdash;/g, '—').replace(/&#171;|&laquo;/g, '«').replace(/&#187;|&raquo;/g, '»')
  .replace(/&#8217;/g, '’').replace(/&quot;/g, '"').replace(/&#0?39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&euro;/g, '€').replace(/&amp;/g, '&').replace(/[ \t]+/g, ' ').trim();

const all = (re: RegExp, s: string) => [...s.matchAll(re)];
const lis = (s: string) => all(/<li>([\s\S]*?)<\/li>/g, s).map((m) => txt(m[1]));

const TOP = new RegExp([
  '<p class="pg-meta">([\\s\\S]*?)<\\/p>',                         // 1 meta
  '<div class="pg-sum">([\\s\\S]*?)<\\/dl><\\/div>',                // 2 sum
  '<nav class="pg-toc"[\\s\\S]*?<\\/nav>',                          //   оглавление не показываем
  '<h2[^>]*>([\\s\\S]*?)<\\/h2>',                                   // 3 h2
  '<h3[^>]*>([\\s\\S]*?)<\\/h3>',                                   // 4 h3
  '<ul class="pg-(list|check)">([\\s\\S]*?)<\\/ul>',                // 5,6 list/check
  '<ol class="pg-steps">([\\s\\S]*?)<\\/ol>',                       // 7 steps
  '<div class="pg-note pg-(tip|warn|info)">([\\s\\S]*?)<\\/div>',   // 8,9 note
  '<div class="pg-table">([\\s\\S]*?)<\\/div>',                     // 10 table
  '<section class="pg-faq">([\\s\\S]*?)<\\/section>',               // 11 faq
  '<div class="pg-cta">[\\s\\S]*?<\\/div>',                         //   призыв к контакт-гайду
  '<div class="pg-src">([\\s\\S]*?)<\\/div>',                       // 12 sources
  '<p(?:\\s[^>]*)?>([\\s\\S]*?)<\\/p>',                             // 13 p (и <p class="wp-block-paragraph"> в новостях)
  '<ul(?:\\s[^>]*)?>([\\s\\S]*?)<\\/ul>',                           // 14 простой список
].join('|'), 'g');

export function parseArticle(html: string): Block[] {
  const out: Block[] = [];
  for (const m of html.matchAll(TOP)) {
    const s = m[0];
    if (m[1] !== undefined) out.push({ t: 'meta', text: txt(m[1]) });
    else if (m[2] !== undefined) out.push({ t: 'sum', rows: all(/<dt>([\s\S]*?)<\/dt><dd>([\s\S]*?)<\/dd>/g, m[2]).map((x) => [txt(x[1]), txt(x[2])]) });
    else if (s.startsWith('<nav')) continue;
    else if (m[3] !== undefined) out.push({ t: 'h2', text: txt(m[3]) });
    else if (m[4] !== undefined) out.push({ t: 'h3', text: txt(m[4]) });
    else if (m[5] !== undefined) out.push({ t: m[5] as 'list' | 'check', items: lis(m[6]) });
    else if (m[7] !== undefined) {
      out.push({ t: 'steps', items: all(/<li>([\s\S]*?)<\/li>/g, m[7]).map((x) => {
        const title = /<p class="pg-step-t">([\s\S]*?)<\/p>/.exec(x[1]);
        return { title: title ? txt(title[1]) : '', text: txt(x[1].replace(/<p class="pg-step-t">[\s\S]*?<\/p>/, '')) };
      }) });
    } else if (m[8] !== undefined) {
      const head = /<p class="pg-note-h">([\s\S]*?)<\/p>/.exec(m[9]);
      out.push({ t: 'note', kind: m[8] as 'tip' | 'warn' | 'info', title: head ? txt(head[1]) : '',
        text: all(/<p>([\s\S]*?)<\/p>/g, m[9]).map((x) => txt(x[1])) });
    } else if (m[10] !== undefined) {
      const head = all(/<th[^>]*>([\s\S]*?)<\/th>/g, m[10]).map((x) => txt(x[1]));
      const body = /<tbody>([\s\S]*?)<\/tbody>/.exec(m[10])?.[1] || '';
      out.push({ t: 'table', head, rows: all(/<tr>([\s\S]*?)<\/tr>/g, body).map((r) => all(/<td[^>]*>([\s\S]*?)<\/td>/g, r[1]).map((x) => txt(x[1]))) });
    } else if (m[11] !== undefined) {
      out.push({ t: 'faq', items: all(/<summary>([\s\S]*?)<\/summary>([\s\S]*?)<\/details>/g, m[11]).map((x) => ({ q: txt(x[1]), a: txt(x[2].replace(/<\/p>\s*<p>/g, '\n\n')) })) });
    } else if (s.startsWith('<div class="pg-cta"')) out.push({ t: 'cta' });
    else if (m[12] !== undefined) {
      out.push({ t: 'src', links: all(/<a [^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g, m[12]).map((x) => ({ url: x[1], title: txt(x[2]) })) });
    } else if (m[13] !== undefined) { const t = txt(m[13]); if (t) out.push({ t: 'p', text: t }); }
    else if (m[14] !== undefined) out.push({ t: 'list', items: lis(m[14]) });
  }
  return out;
}
