import { router, useLocalSearchParams } from 'expo-router';
import { Platform, ScrollView, Share, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { toggleFavorite, useAuth } from '@/api/auth';
import { SITE } from '@/api/client';
import { useContent } from '@/api/content';
import { dayMonth, weekday } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { BackButton, Button, Empty, Glass, Icon, IconButton, IconName, Img, Skeleton, Txt, useToast } from '@/ui';

function Info({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
      <View style={{ width: 40, height: 40, borderRadius: 13, backgroundColor: c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} size={19} />
      </View>
      <View style={{ flex: 1 }}>
        <Txt v="caption">{label}</Txt>
        <Txt v="bodyStrong">{value}</Txt>
      </View>
    </View>
  );
}

export default function EventScreen() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useContent();
  const { user, favorites } = useAuth();
  const e = q.data?.events.find((x) => x.key === String(key));

  if (!e) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 8, paddingHorizontal: 14 }}>
        <BackButton />
        {q.isLoading ? <View style={{ gap: 12, marginTop: 20 }}><Skeleton h={380} r={28} /><Skeleton w="70%" h={26} /></View>
          : <Empty icon="ticket" title="Событие не найдено" text="Возможно, оно уже прошло." />}
      </View>
    );
  }
  const fav = favorites.some((f) => f.key === e.key);
  const heart = () => (user ? toggleFavorite(e.key, e.h, !fav).then(() => toast(fav ? 'Убрано из избранного' : 'Добавлено в избранное')).catch(() => {}) : router.push('/login'));
  const when = `${weekday(e.date)}, ${dayMonth(e.date)}${e.end && e.end !== e.date ? ` — ${dayMonth(e.end)}` : ''}`;
  const ticket = e.tickets?.[0]?.[2] || e.url;
  const share = async () => {
    const url = `${SITE}/events/${e.key}/`;
    try {
      if (Platform.OS === 'web') {
        const nav = (globalThis as any).navigator;
        if (nav?.share) await nav.share({ title: e.h, url }); else { await nav?.clipboard?.writeText(url); toast('Ссылка скопирована'); }
      } else await Share.share({ message: `${e.h}\n${url}` });
    } catch { /* отменено */ }
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bgElevated }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 130 + insets.bottom }}>
        {e.img ? <Img source={e.img} style={{ width: '100%', aspectRatio: 4 / 5, maxHeight: 560 }} /> : <View style={{ height: insets.top + 70, backgroundColor: c.bg }} />}
        <View style={{ marginTop: e.img ? -30 : 0, backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xxl, borderTopRightRadius: radius.xxl, padding: 22, gap: 18 }}>
          <View style={{ gap: 8 }}>
            <Txt v="overline" tone="accent">{e.cat || 'Событие'}</Txt>
            <Txt v="title1">{e.h}</Txt>
            {e.s ? <Txt v="callout" tone="muted">{e.s}</Txt> : null}
          </View>
          <View style={{ gap: 14 }}>
            <Info icon="calendar" label="Когда" value={`${when}${e.time ? ` · ${e.time}` : ''}`} />
            {e.venue ? <Info icon="location" label="Где" value={[e.venue, e.addr || e.city].filter(Boolean).join(', ')} /> : null}
            {e.price ? <Info icon="euro" label="Цена" value={e.price} /> : null}
          </View>
          {(e.p || []).map((t, i) => <Txt key={i} v="body" style={{ lineHeight: 25 }}>{t}</Txt>)}
          <Button title="Открыть на сайте" kind="secondary" icon="globe" onPress={() => openUrl(`${SITE}/events/${e.key}/`)} />
        </View>
      </ScrollView>
      <View pointerEvents="box-none" style={{ position: 'absolute', top: insets.top + 8, left: 14, right: 14, flexDirection: 'row', justifyContent: 'space-between' }}>
        <BackButton />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <IconButton icon="share" label="Поделиться" onPress={share} />
          <IconButton icon={fav ? 'heartFill' : 'heart'} label={fav ? 'Убрать из избранного' : 'В избранное'} onPress={heart} color={fav ? c.accent : undefined} />
        </View>
      </View>
      {ticket ? (
        <View style={{ position: 'absolute', left: 12, right: 12, bottom: insets.bottom + 12 }}>
          <Glass radius={radius.xxl} strong style={{ padding: 8 }}>
            <Button title={e.price ? `Билеты · ${e.price}` : 'Билеты'} kind="primary" icon="ticket" onPress={() => openUrl(ticket)} />
          </Glass>
        </View>
      ) : null}
    </View>
  );
}
