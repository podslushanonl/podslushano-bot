import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { Button, Icon, Tap, Txt } from '@/ui';
import type { Block } from './parse';

const NOTE = { tip: { icon: 'sparkles', title: 'Совет' }, warn: { icon: 'warning', title: 'Важно' }, info: { icon: 'info', title: 'Полезно знать' } } as const;

/** Вопрос-ответ: раскрывается по нажатию. */
function Faq({ q, a, first }: { q: string; a: string; first: boolean }) {
  const { c } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <View style={{ borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <Tap onPress={() => setOpen(!open)} scaleTo={0.99} accessibilityRole="button" accessibilityState={{ expanded: open }}
        style={{ flexDirection: 'row', gap: 12, alignItems: 'center', paddingVertical: 14, paddingHorizontal: 16 }}>
        <Txt v="bodyStrong" style={{ flex: 1 }}>{q}</Txt>
        <View style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }}><Icon name="down" size={14} color={c.muted} /></View>
      </Tap>
      {open ? <Txt v="body" style={{ paddingHorizontal: 16, paddingBottom: 16 }}>{a}</Txt> : null}
    </View>
  );
}

/** Один блок статьи справочника в стиле приложения. */
export function ArticleBlock({ b }: { b: Block }) {
  const { c } = useTheme();
  const card = { backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line } as const;
  switch (b.t) {
    case 'meta': return <Txt v="footnote">{b.text}</Txt>;
    case 'sum': return (
      <View style={[card, { padding: 16, gap: 12, backgroundColor: c.accentSoft, borderColor: c.accentSoft }]}>
        <Txt v="overline" tone="accent">Коротко</Txt>
        {b.rows.map(([k, v]) => (
          <View key={k} style={{ gap: 2 }}>
            <Txt v="subhead" tone="ink" style={{ fontWeight: '700' }}>{k}</Txt>
            <Txt v="callout" tone="text">{v}</Txt>
          </View>
        ))}
      </View>
    );
    case 'h2': return <Txt v="title2" accessibilityRole="header" style={{ marginTop: 10 }}>{b.text}</Txt>;
    case 'h3': return <Txt v="headline" accessibilityRole="header">{b.text}</Txt>;
    case 'p': return <Txt v="body">{b.text}</Txt>;
    case 'list': return (
      <View style={{ gap: 8 }}>
        {b.items.map((x, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 10 }}>
            <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: c.accent, marginTop: 9 }} />
            <Txt v="body" style={{ flex: 1 }}>{x}</Txt>
          </View>
        ))}
      </View>
    );
    case 'check': return (
      <View style={[card, { padding: 16, gap: 12 }]}>
        {b.items.map((x, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 10 }}>
            <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
              <Icon name="check" size={13} color={c.accentText} />
            </View>
            <Txt v="callout" tone="text" style={{ flex: 1 }}>{x}</Txt>
          </View>
        ))}
      </View>
    );
    case 'steps': return (
      <View style={{ gap: 0 }}>
        {b.items.map((s, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 14 }}>
            <View style={{ alignItems: 'center' }}>
              <View style={{ width: 30, height: 30, borderRadius: 15, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
                <Txt v="subhead" color={c.onAccent} style={{ fontWeight: '700' }}>{i + 1}</Txt>
              </View>
              {i < b.items.length - 1 ? <View style={{ width: 2, flex: 1, backgroundColor: c.line, marginVertical: 4 }} /> : null}
            </View>
            <View style={{ flex: 1, gap: 4, paddingBottom: i < b.items.length - 1 ? 18 : 0, paddingTop: 4 }}>
              {s.title ? <Txt v="headline">{s.title}</Txt> : null}
              {s.text ? <Txt v="callout" tone="text">{s.text}</Txt> : null}
            </View>
          </View>
        ))}
      </View>
    );
    case 'note': {
      const n = NOTE[b.kind];
      const tint = b.kind === 'warn' ? c.danger : b.kind === 'tip' ? c.success : c.info;
      return (
        <View style={[card, { padding: 16, gap: 8, borderColor: tint }]}>
          <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
            <Icon name={n.icon} size={18} color={tint} />
            <Txt v="subhead" color={tint} style={{ fontWeight: '700' }}>{b.title || n.title}</Txt>
          </View>
          {b.text.map((x, i) => <Txt key={i} v="callout" tone="text">{x}</Txt>)}
        </View>
      );
    }
    case 'table': return (
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -16 }} contentContainerStyle={{ paddingHorizontal: 16 }}>
        <View style={[card, { overflow: 'hidden' }]}>
          <View style={{ flexDirection: 'row', backgroundColor: c.bgSunken }}>
            {b.head.map((h, i) => <Txt key={i} v="footnote" tone="ink" style={{ width: 200, padding: 12, fontWeight: '700' }}>{h}</Txt>)}
          </View>
          {b.rows.map((r, i) => (
            <View key={i} style={{ flexDirection: 'row', borderTopWidth: 1, borderTopColor: c.line }}>
              {r.map((x, j) => <Txt key={j} v="subhead" tone="text" style={{ width: 200, padding: 12 }}>{x}</Txt>)}
            </View>
          ))}
        </View>
      </ScrollView>
    );
    case 'faq': return (
      <View style={{ gap: 10 }}>
        <Txt v="title2" accessibilityRole="header" style={{ marginTop: 10 }}>Частые вопросы</Txt>
        <View style={[card, { overflow: 'hidden' }]}>{b.items.map((x, i) => <Faq key={i} q={x.q} a={x.a} first={i === 0} />)}</View>
      </View>
    );
    case 'cta': return (
      <View style={[card, { padding: 16, gap: 10 }]}>
        <Txt v="headline">Нужен специалист, который говорит по-русски?</Txt>
        <Txt v="callout" tone="muted">Юристы, бухгалтеры, врачи и консультанты вашей провинции — в контакт-гайде.</Txt>
        <Button kind="secondary" size="s" full={false} icon="people" title="Открыть контакт-гайд" onPress={() => router.push('/guide')} />
      </View>
    );
    case 'src': return (
      <View style={{ gap: 8 }}>
        <Txt v="overline">Официальные источники</Txt>
        {b.links.map((l) => (
          <Tap key={l.url} onPress={() => openUrl(l.url)} style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }} accessibilityRole="link">
            <Icon name="link" size={15} color={c.accentText} />
            <Txt v="subhead" tone="accent" style={{ flex: 1 }}>{l.title}</Txt>
          </Tap>
        ))}
      </View>
    );
  }
}
