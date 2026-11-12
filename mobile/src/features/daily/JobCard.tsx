import { useState } from 'react';
import { View } from 'react-native';
import { Job } from '@/api/content';
import { ago } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Button, Icon, Tap, Txt } from '@/ui';

/** Карточка вакансии: коротко, по нажатию — описание и кнопка «Откликнуться». */
export function JobCard({ j, compact }: { j: Job; compact?: boolean }) {
  const { c } = useTheme();
  const [open, setOpen] = useState(false);
  const meta = [j.city, j.type].filter(Boolean).join(' · ');
  return (
    <Tap onPress={() => setOpen((o) => !o)} scaleTo={0.99} accessibilityLabel={`${j.title}, ${j.company || ''}`}
      style={{ backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: HAIRLINE, borderColor: c.line, padding: 16, gap: 6 }}>
      <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12 }}>
        <View style={{ width: 40, height: 40, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="briefcase" size={20} color={c.accentText} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Txt v="headline" numberOfLines={compact && !open ? 2 : undefined}>{j.title}</Txt>
          {j.company ? <Txt v="subhead" tone="muted" numberOfLines={1}>{j.company}</Txt> : null}
          {meta ? <Txt v="footnote">{meta}</Txt> : null}
        </View>
      </View>
      {j.salary ? <Txt v="subhead" style={{ fontWeight: '600' }}>{j.salary}</Txt> : null}
      {open ? (
        <View style={{ gap: 10, marginTop: 4 }}>
          {j.lang ? <Txt v="footnote" tone="accent">Язык: {j.lang}</Txt> : null}
          {j.about ? <Txt v="callout">{j.about}</Txt> : null}
          {j.posted ? <Txt v="footnote">Опубликовано {ago(j.posted)}</Txt> : null}
          {j.url ? <Button kind="accent" icon="link" title="Откликнуться" onPress={() => openUrl(j.url!)} /> : null}
        </View>
      ) : <Txt v="footnote" tone="accent">Подробнее</Txt>}
    </Tap>
  );
}
