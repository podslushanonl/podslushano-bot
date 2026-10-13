import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { NativeScrollEvent, NativeSyntheticEvent, Platform, ScrollView, Share, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { toggleFavorite, useAuth } from '@/api/auth';
import { BOT } from '@/api/client';
import { routeForError } from '@/api/community';
import { startDialog } from '@/api/dm';
import { absUrl, CAT_ICON, closeListing, marketChanged, payListing, REPORT_REASONS, reportListing, useListing } from '@/api/market';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { ActionSheet, BackButton, Button, Empty, Glass, Icon, IconButton, IconName, Img, Skeleton, Tap, Txt, useToast } from '@/ui';

const SOCIAL: Record<string, any> = {
  telegram: require('@assets/images/social/telegram.png'),
  instagram: require('@assets/images/social/instagram.png'),
  whatsapp: require('@assets/images/social/whatsapp.png'),
};
const SYS: Record<string, IconName> = { phone: 'phone', email: 'mail', website: 'globe' };

/** Фото объявления: листаются пальцем, счётчик на стекле. */
function Gallery({ urls, cat }: { urls: string[]; cat: string }) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const [i, setI] = useState(0);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => setI(Math.round(e.nativeEvent.contentOffset.x / Math.max(1, width)));
  if (!urls.length) {
    return (
      <View style={{ height: 380, alignItems: 'center', justifyContent: 'center', backgroundColor: c.accentSoft }}>
        <Icon name={CAT_ICON[cat] || 'box'} size={64} color={c.accentText} />
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
  const fav = favorites.some((f) => f.kind === 'listing' && f.key === String(id));
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
  const contacts = l.contacts || [];
  const main = contacts[0];

  return (
    <View style={{ flex: 1, backgroundColor: c.bgElevated }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 140 + insets.bottom }}>
        <Gallery urls={(l.photos?.length ? l.photos : l.photo ? [l.photo] : []).map(absUrl)} cat={l.cat} />
        <View style={{ marginTop: -30, backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xxl, borderTopRightRadius: radius.xxl, padding: 22, gap: 18 }}>
          {l.mine ? (
            <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.l, padding: 16, gap: 10 }}>
              <Txt v="overline" tone="accent">Моё объявление · {l.status_title}</Txt>
              <Txt v="callout" tone="ink">
                {l.status === 'pending' ? 'Модератор проверит его в ближайшее время — обычно в течение дня.'
                  : l.status === 'rejected' ? 'Не прошло проверку. Исправьте и отправьте снова.'
                  : l.status === 'awaiting_payment' ? 'Размещение жилья платное. После оплаты объявление уйдёт на проверку.'
                  : l.until ? `Опубликовано до ${l.until.split('-').reverse().join('.')}` : 'Объявление снято с публикации.'}
              </Txt>
              {l.status === 'awaiting_payment' ? <Button title="Оплатить размещение" kind="accent" loading={busy}
                onPress={() => run(async () => { const d = await payListing(l.id); await WebBrowser.openBrowserAsync(d.pay_url); q.refetch(); })} /> : null}
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Button title="Изменить" kind="secondary" size="s" icon="edit" style={{ flex: 1 }}
                  onPress={() => router.push({ pathname: '/market/new', params: { id: String(l.id) } })} />
                {l.status !== 'closed' ? <Button title="Снять" kind="danger" size="s" icon="trash" style={{ flex: 1 }} loading={busy}
                  onPress={() => run(async () => { await closeListing(l.id); marketChanged(); router.back(); }, 'Объявление снято')} /> : null}
              </View>
            </View>
          ) : null}

          <View style={{ gap: 8 }}>
            <Txt v="overline">{[l.cat_title, l.intent_title].filter(Boolean).join(' · ')}</Txt>
            {l.price ? <Txt v="display" style={{ fontSize: 30, lineHeight: 35 }}>{l.price}</Txt> : null}
            <Txt v="title3">{l.title}</Txt>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Icon name="location" size={15} color={c.muted} />
              <Txt v="subhead" tone="muted">{l.city || 'Нидерланды'}</Txt>
            </View>
          </View>

          {l.description ? <Txt v="body" tone="text" style={{ lineHeight: 25 }}>{l.description}</Txt> : null}

          {l.cat === 'housing' ? (
            <View style={{ flexDirection: 'row', gap: 12, backgroundColor: c.bgSunken, borderRadius: radius.l, padding: 14 }}>
              <Icon name="shield" size={20} color={c.success} />
              <Txt v="callout" tone="ink" style={{ flex: 1 }}>Не переводите предоплату, пока не увидели жильё и договор.</Txt>
            </View>
          ) : null}

          {!l.mine && contacts.length > 1 ? (
            <View style={{ gap: 10 }}>
              <Txt v="overline">Все способы связи</Txt>
              {contacts.map((ct) => (
                <Tap key={ct.type + ct.url} onPress={() => openUrl(ct.url)} scaleTo={0.98}
                  style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: radius.l, borderWidth: 1, borderColor: c.line }}>
                  {SOCIAL[ct.type] ? <Img source={SOCIAL[ct.type]} style={{ width: 32, height: 32, backgroundColor: 'transparent' }} />
                    : <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: c.inverse, alignItems: 'center', justifyContent: 'center' }}>
                        <Icon name={SYS[ct.type] || 'globe'} size={15} color={c.onInverse} /></View>}
                  <Txt v="bodyStrong" style={{ flex: 1 }}>{ct.title}</Txt>
                  <Icon name="chevron" size={14} color={c.faint} />
                </Tap>
              ))}
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
            onPress={() => (user ? toggleFavorite(String(l.id), l.title, !fav, 'listing').then(() => toast(fav ? 'Убрано из избранного' : 'Добавлено в избранное')).catch(() => {}) : router.push('/login'))} /> : null}
        </View>
      </View>

      {!l.mine && (l.chat || main) ? (
        <View style={{ position: 'absolute', left: 12, right: 12, bottom: insets.bottom + 12 }}>
          <Glass radius={radius.xxl} strong style={{ padding: 8, flexDirection: 'row', gap: 8 }}>
            {l.chat ? (
              <Button title="Написать продавцу" kind="primary" icon="bubble" style={{ flex: 1 }} loading={busy}
                onPress={() => (user ? run(async () => {
                  const d = await startDialog(l.id);
                  router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
                }) : router.push('/login'))} />
            ) : (
              <Button title={main!.type === 'phone' ? 'Позвонить' : main!.type === 'email' ? 'Написать на почту' : `Написать в ${main!.title}`}
                kind="primary" icon={main!.type === 'phone' ? 'phone' : 'bubble'} style={{ flex: 1 }} onPress={() => openUrl(main!.url)} />
            )}
            {l.chat && main ? (
              <Tap onPress={() => openUrl(main.url)} scaleTo={0.9} accessibilityLabel={main.title}
                style={{ width: 54, height: 54, borderRadius: 27, backgroundColor: c.bgElevated, borderWidth: 1, borderColor: c.line, alignItems: 'center', justifyContent: 'center' }}>
                {SOCIAL[main.type] ? <Img source={SOCIAL[main.type]} style={{ width: 30, height: 30, backgroundColor: 'transparent' }} />
                  : <Icon name={SYS[main.type] || 'globe'} size={21} />}
              </Tap>
            ) : null}
          </Glass>
        </View>
      ) : null}

      <ActionSheet visible={reportOpen} title="Что не так с объявлением?" onClose={() => setReportOpen(false)}
        actions={REPORT_REASONS.map(([key, title]) => ({ title, onPress: () => run(() => reportListing(l.id, key), 'Спасибо! Передали модераторам.') }))} />
    </View>
  );
}
