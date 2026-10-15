import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { NativeScrollEvent, NativeSyntheticEvent, Platform, ScrollView, Share, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { toggleFavorite, useAuth } from '@/api/auth';
import { BOT } from '@/api/client';
import { routeForError } from '@/api/community';
import { startDialog } from '@/api/dm';
import { absUrl, CAT_ICON, closeListing, marketChanged, REPORT_REASONS, reportListing, useListing } from '@/api/market';
import { ago } from '@/lib/format';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Avatar, BackButton, Button, Empty, Glass, Icon, IconButton, Skeleton, Tap, Txt, useToast } from '@/ui';

/** Фото объявления: листаются пальцем, счётчик на стекле. */
function Gallery({ urls, cat }: { urls: string[]; cat: string }) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const [i, setI] = useState(0);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => setI(Math.round(e.nativeEvent.contentOffset.x / Math.max(1, width)));
  if (!urls.length) {
    return (
      <View style={{ height: 380, alignItems: 'center', justifyContent: 'center', backgroundColor: c.bgSunken }}>
        <Icon name={CAT_ICON[cat] || 'box'} thin size={64} color={c.faint} />
      </View>
    );
  }
  return (
    <View style={{ height: 440, backgroundColor: c.placeholder }}>
      <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false} onScroll={onScroll} scrollEventThrottle={32}>
        {urls.map((u) => <Image key={u} source={u} style={{ width, height: 440 }} contentFit="cover" transition={200} />)}
      </ScrollView>
      {urls.length > 1 ? (
        <View pointerEvents="none" style={{ position: 'absolute', bottom: 44, alignSelf: 'center' }}>
          <Glass radius={radius.pill} strong style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 7 }}>
            {urls.map((u, k) => <View key={u} style={{ width: k === i ? 16 : 6, height: 6, borderRadius: 3, backgroundColor: k === i ? c.ink : c.faint }} />)}
          </Glass>
        </View>
      ) : null}
    </View>
  );
}

export default function ListingScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user, favorites } = useAuth();
  const q = useListing(Number(id));
  const fav = favorites.some((f) => f.kind === 'item' && f.key === String(id));
  const l = q.data;
  const [reportOpen, setReportOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const share = async () => {
    const url = `${BOT}/app/market/${id}`;
    try {
      if (Platform.OS === 'web') {
        const nav = (globalThis as any).navigator;
        if (nav?.share) await nav.share({ title: l?.title, url });
        else { await nav?.clipboard?.writeText(url); toast('Ссылка скопирована'); }
      } else await Share.share({ message: `${l?.title}\n${url}` });
    } catch { /* отменено */ }
  };

  if (q.isLoading) {
    return <View style={{ flex: 1, backgroundColor: c.bg }}><Skeleton h={380} r={0} /><View style={{ padding: 20, gap: 12 }}><Skeleton w={120} h={30} /><Skeleton w="80%" h={22} /><Skeleton w="50%" /></View></View>;
  }
  if (!l) {
    return (
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 12, paddingHorizontal: 12 }}>
        <BackButton />
        <Empty icon="market" title="Объявление недоступно" text={(q.error as any)?.message || 'Его сняли с публикации или ещё не проверили.'}
          action={<Button title="К барахолке" kind="secondary" onPress={() => router.replace('/market')} />} />
      </View>
    );
  }

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast(ok); } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bgElevated }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 140 + insets.bottom }}>
        <Gallery urls={(l.photos?.length ? l.photos : l.photo ? [l.photo] : []).map(absUrl)} cat={l.cat} />
        <View style={{ marginTop: -30, backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xxl, borderTopRightRadius: radius.xxl, padding: 22, gap: 18 }}>
          {l.mine ? (
            <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.l, padding: 16, gap: 10 }}>
              <Txt v="overline" tone="accent">Моё объявление · {l.status_title}</Txt>
              <Txt v="callout" tone="ink">
                {l.status === 'active' ? `Опубликовано до ${(l.until || '').split('-').reverse().join('.')}`
                  : l.status === 'hidden' ? 'Скрыто после жалоб — модератор посмотрит его в ближайшее время.'
                  : l.status === 'removed' ? 'Удалено модератором за нарушение правил сообщества.'
                  : l.status === 'expired' ? 'Срок публикации истёк. Сохраните объявление снова, чтобы продлить его на 30 дней.'
                  : 'Объявление снято с публикации. Сохраните его снова, чтобы опубликовать.'}
              </Txt>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                {l.status !== 'hidden' && l.status !== 'removed' ? <Button title={l.status === 'active' ? 'Изменить' : 'Опубликовать снова'} kind="secondary" size="s" icon="edit" style={{ flex: 1 }}
                  onPress={() => router.push({ pathname: '/market/new', params: { id: String(l.id) } })} /> : null}
                {l.status === 'active' ? <Button title="Снять" kind="danger" size="s" icon="trash" style={{ flex: 1 }} loading={busy}
                  onPress={() => run(async () => { await closeListing(l.id); marketChanged(); router.back(); }, 'Объявление снято')} /> : null}
              </View>
            </View>
          ) : null}

          <View style={{ gap: 8 }}>
            <Txt v="overline">{l.cat_title}</Txt>
            <Txt v="display" color={l.price_value === 0 ? c.accent : c.ink} style={{ fontSize: 30, lineHeight: 35 }}>{l.price}</Txt>
            <Txt v="title3">{l.title}</Txt>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Icon name="location" size={15} color={c.muted} />
              <Txt v="subhead" tone="muted">{[l.city, ago(l.at.slice(0, 10))].filter(Boolean).join(' · ')}</Txt>
            </View>
          </View>

          {l.description ? <Txt v="body" tone="text" style={{ lineHeight: 25 }}>{l.description}</Txt> : null}

          {l.seller && !l.mine ? (
            <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(l.seller!.id) } })} scaleTo={0.98}
              accessibilityLabel={`Продавец: ${l.seller.name}`}
              style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: radius.l, backgroundColor: c.bgSunken }}>
              <Avatar name={l.seller.name} id={l.seller.id} uri={l.seller.avatar} size={46} />
              <View style={{ flex: 1, gap: 2 }}>
                <Txt v="bodyStrong" numberOfLines={1}>{l.seller.name}</Txt>
                <Txt v="footnote" tone="muted" numberOfLines={1}>
                  {[l.seller.city, l.seller.since ? `в podslushano с ${l.seller.since.slice(0, 4)}` : ''].filter(Boolean).join(' · ')}
                </Txt>
              </View>
              <Icon name="chevron" size={14} color={c.faint} />
            </Tap>
          ) : null}

          {l.cat === 'housing' || l.cat === 'tickets' ? (
            <View style={{ flexDirection: 'row', gap: 12, backgroundColor: c.bgSunken, borderRadius: radius.l, padding: 14 }}>
              <Icon name="shield" size={20} color={c.success} />
              <Txt v="callout" tone="ink" style={{ flex: 1 }}>
                {l.cat === 'housing' ? 'Не переводите предоплату, пока не увидели жильё и договор.' : 'Не платите за билеты заранее незнакомым людям — встречайтесь лично или проверяйте билет через организатора.'}
              </Txt>
            </View>
          ) : null}

          {!l.mine ? (
            <Tap onPress={() => (user ? setReportOpen(true) : router.push('/login'))} style={{ alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 6, padding: 10 }}>
              <Icon name="flag" size={15} color={c.muted} />
              <Txt v="subhead" tone="muted">Пожаловаться на объявление</Txt>
            </Tap>
          ) : null}
        </View>
      </ScrollView>

      <View pointerEvents="box-none" style={{ position: 'absolute', top: insets.top + 8, left: 14, right: 14, flexDirection: 'row', justifyContent: 'space-between' }}>
        <BackButton />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <IconButton icon="share" label="Поделиться" onPress={share} />
          {!l.mine ? <IconButton icon={fav ? 'heartFill' : 'heart'} label={fav ? 'Убрать из избранного' : 'В избранное'} color={fav ? c.accent : undefined}
            onPress={() => (user ? toggleFavorite(String(l.id), l.title, !fav, 'item').then(() => toast(fav ? 'Убрано из избранного' : 'Добавлено в избранное')).catch(() => {}) : router.push('/login'))} /> : null}
        </View>
      </View>

      {!l.mine && l.chat ? (
        <View style={{ position: 'absolute', left: 12, right: 12, bottom: insets.bottom + 12 }}>
          <Glass radius={radius.xxl} strong style={{ padding: 8 }}>
            <Button title="Написать продавцу" kind="accent" icon="bubble" loading={busy}
              onPress={() => (user ? run(async () => {
                const d = await startDialog(l.id);
                router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
              }) : router.push('/login'))} />
          </Glass>
        </View>
      ) : null}

      <ActionSheet visible={reportOpen} title="Что не так с объявлением?" onClose={() => setReportOpen(false)}
        actions={REPORT_REASONS.map(([key, title]) => ({ title, onPress: () => run(() => reportListing(l.id, key), 'Спасибо! Передали модераторам.') }))} />
    </View>
  );
}
