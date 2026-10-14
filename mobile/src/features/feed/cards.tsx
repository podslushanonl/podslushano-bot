import { router } from 'expo-router';
import { View } from 'react-native';
import { EventItem, Job, News } from '@/api/content';
import { Msg } from '@/api/community';
import { goUrl } from '@/api/client';
import { ago, dayMonth, weekday } from '@/lib/format';
import { openBot, openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { Avatar, Button, Card, Icon, IconButton, Img, Tap, Txt } from '@/ui';

export function timeLabel(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const hm = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Amsterdam' });
  if (d.toDateString() === now.toDateString()) return hm;
  return `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: 'Europe/Amsterdam' })}, ${hm}`;
}

export function NewsCard({ n, big }: { n: News; big?: boolean }) {
  const { c } = useTheme();
  if (!big || !n.img) {
    return (
      <Tap onPress={() => openUrl(n.link)} scaleTo={0.985} style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated,
        borderRadius: radius.xl, padding: 12, borderWidth: 1, borderColor: c.line }}>
        <View style={{ flex: 1, gap: 5, paddingLeft: 4 }}>
          <Txt v="overline">{n.cat} · {ago(n.date, n.time)}</Txt>
          <Txt v="headline" numberOfLines={3}>{n.h}</Txt>
        </View>
        {n.img ? <Img source={n.thumb || n.img} style={{ width: 92, height: 92, borderRadius: 18 }} /> : null}
      </Tap>
    );
  }
  return (
    <Tap onPress={() => openUrl(n.link)} scaleTo={0.985} style={{ borderRadius: radius.xxl, overflow: 'hidden', backgroundColor: c.bgElevated, borderWidth: 1, borderColor: c.line }}>
      <Img source={n.img} style={{ width: '100%', aspectRatio: 16 / 10 }} />
      <View style={{ padding: 18, gap: 8 }}>
        <Txt v="overline">{n.cat} · {ago(n.date, n.time)}</Txt>
        <Txt v="title3">{n.h}</Txt>
        {n.lead ? <Txt v="callout" tone="muted" numberOfLines={3}>{n.lead}</Txt> : null}
      </View>
    </Tap>
  );
}

export function EventCard({ e }: { e: EventItem }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} scaleTo={0.985}
      style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.xl, padding: 12, borderWidth: 1, borderColor: c.line }}>
      {e.img ? <Img source={e.img} style={{ width: 78, height: 98, borderRadius: 16 }} />
        : <View style={{ width: 78, height: 98, borderRadius: 16, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}><Icon name="ticket" color={c.accentText} /></View>}
      <View style={{ flex: 1, gap: 4 }}>
        <Txt v="overline" tone="accent">{weekday(e.date)}, {dayMonth(e.date)}{e.time ? ` · ${e.time}` : ''}</Txt>
        <Txt v="headline" numberOfLines={2}>{e.h}</Txt>
        <Txt v="footnote" numberOfLines={1}>{[e.venue, e.city].filter(Boolean).join(', ')}</Txt>
        {e.price ? <Txt v="footnote" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{e.price}</Txt> : null}
      </View>
    </Tap>
  );
}

export function JobCard({ j }: { j: Job }) {
  const { c } = useTheme();
  return (
    <Card onPress={() => j.url && openUrl(j.url)}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <View style={{ width: 30, height: 30, borderRadius: 9, backgroundColor: c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="briefcase" size={16} />
        </View>
        <Txt v="overline">Работа · {j.city || 'Нидерланды'}</Txt>
      </View>
      <Txt v="headline">{j.title}</Txt>
      <Txt v="footnote" numberOfLines={2}>{[j.company, j.salary, j.lang && `язык: ${j.lang}`].filter(Boolean).join(' · ')}</Txt>
    </Card>
  );
}

export function PostCard({ p, onMenu }: { p: Msg; onMenu: () => void }) {
  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(p.author.id) } })} scaleTo={0.98}
          accessibilityLabel={`Профиль: ${p.author.name}`} style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <Avatar name={p.author.name} id={p.author.id} size={42} />
          <View style={{ flex: 1 }}>
            <Txt v="headline">{p.author.name}</Txt>
            <Txt v="footnote">{[p.city || p.author.city, timeLabel(p.at)].filter(Boolean).join(' · ')}</Txt>
          </View>
        </Tap>
        <IconButton icon="more" label="Действия с постом" onPress={onMenu} kind="plain" size={36} />
      </View>
      <Txt v="body" tone="ink">{p.text}</Txt>
    </Card>
  );
}

export function SaveCard() {
  const { c } = useTheme();
  return (
    <View style={{ backgroundColor: c.hero, borderRadius: radius.xxl, padding: 20, gap: 10 }}>
      <Txt v="overline" color={c.accent}>Сэкономить · до 31 декабря</Txt>
      <Txt v="title2" color={c.onHero}>Не переплачивайте за медстраховку в 2027</Txt>
      <Txt v="callout" color={c.onHeroMuted}>Базовый пакет у всех страховщиков одинаковый, разница — только в цене. 6 вопросов — и вы знаете, на что смотреть.</Txt>
      <View style={{ flexDirection: 'row', gap: 10, marginTop: 6 }}>
        <Button title="6 вопросов" kind="accent" size="s" full={false} onPress={() => openBot('save_zorg')} />
        <Button title="Сравнить цены" kind="glass" size="s" full={false} onPress={() => openUrl(goUrl('zorg_compare'))} />
      </View>
    </View>
  );
}
