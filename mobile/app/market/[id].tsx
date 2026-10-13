import { Image } from 'expo-image';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import { Alert, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ActionSheet } from '@/components/ActionSheet';
import { MarketIcon } from '@/components/MarketIcon';
import { Button, Card, ErrorBox, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { ApiError } from '@/lib/auth';
import { routeForError } from '@/lib/community';
import { REPORT_REASONS, Listing, closeListing, getListing, notifyMarketChanged, payListing, photoUrl, reportListing } from '@/lib/market';

const SOCIAL: Record<string, any> = {
  telegram: require('@/assets/images/social/telegram.png'),
  instagram: require('@/assets/images/social/instagram.png'),
  whatsapp: require('@/assets/images/social/whatsapp.png'),
};

const say = (msg: string) => (Platform.OS === 'web' ? (globalThis as any).alert(msg) : Alert.alert('', msg));

function confirm(msg: string, ok: () => void) {
  if (Platform.OS === 'web') { if ((globalThis as any).confirm(msg)) ok(); return; }
  Alert.alert('', msg, [{ text: 'Отмена', style: 'cancel' }, { text: 'Да', style: 'destructive', onPress: ok }]);
}

export default function ListingScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [l, setL] = useState<Listing | null>(null);
  const [error, setError] = useState('');
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setL(await getListing(Number(id))); setError(''); }
    catch (e) { setError(e instanceof ApiError && e.status === 404 ? e.message : 'net'); }
  }, [id]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);

  if (error === 'net') return <ErrorBox onRetry={load} />;
  if (error) return <View style={{ padding: 24, gap: 12 }}><P muted>{error}</P><Button title="К барахолке" soft onPress={() => router.back()} /></View>;
  if (!l) return <Loading />;

  const open = (url: string) => (url.startsWith('http') ? WebBrowser.openBrowserAsync(url) : Linking.openURL(url));
  const doReport = async (reason: string) => {
    try { await reportListing(l.id, reason); say('Спасибо! Передали модераторам.'); }
    catch (e: any) { if (!routeForError(e)) say(e?.message || 'Не отправилось'); }
  };
  const doClose = () => confirm('Снять объявление с публикации?', async () => {
    setBusy(true);
    try { await closeListing(l.id); notifyMarketChanged(); router.back(); }
    catch (e: any) { say(e?.message || 'Не получилось'); }
    finally { setBusy(false); }
  });
  const doPay = async () => {
    setBusy(true);
    try { const d = await payListing(l.id); await WebBrowser.openBrowserAsync(d.pay_url); load(); }
    catch (e: any) { say(e?.message || 'Не получилось'); }
    finally { setBusy(false); }
  };

  return (
    <>
      <Stack.Screen options={{ title: l.cat_title }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        {l.photo ? <Image source={{ uri: photoUrl(l) }} style={s.photo} contentFit="cover" transition={150} /> : null}
        <View style={{ padding: 16, gap: 14 }}>
          {l.mine ? (
            <Card style={{ backgroundColor: C.accentSoft, borderColor: C.accentSoft }}>
              <Eyebrow>Моё объявление · {l.status_title}</Eyebrow>
              {l.status === 'pending' ? <P>Модератор проверит его в ближайшее время.</P> : null}
              {l.status === 'rejected' ? <P>Не прошло проверку. Исправьте и отправьте снова.</P> : null}
              {l.status === 'awaiting_payment' ? <P>Размещение жилья платное. После оплаты объявление уйдёт на проверку.</P> : null}
              {l.until ? <P muted>Опубликовано до {l.until.split('-').reverse().join('.')}</P> : null}
              {l.status === 'awaiting_payment' ? <Button title="Оплатить размещение" onPress={doPay} disabled={busy} /> : null}
              <Button title="Изменить" soft onPress={() => router.push({ pathname: '/market/new', params: { id: String(l.id) } })} />
              {l.status !== 'closed' ? <Button title="Снять с публикации" soft onPress={doClose} disabled={busy} /> : null}
            </Card>
          ) : null}
          <View style={{ gap: 6 }}>
            <Eyebrow>{[l.cat_title, l.intent_title].filter(Boolean).join(' · ')}</Eyebrow>
            <H size={24}>{l.title}</H>
            {l.price ? <Text style={s.price}>{l.price}</Text> : null}
            {l.city ? <P muted>{l.city}</P> : null}
          </View>
          {l.description ? <P>{l.description}</P> : null}
          {l.cat === 'housing' ? (
            <Card style={{ backgroundColor: '#FFF6E0', borderColor: '#FFE6A8' }}>
              <P>Не переводите предоплату, пока не увидели жильё и договор.</P>
            </Card>
          ) : null}
          {!l.mine && l.contacts?.length ? (
            <View style={{ gap: 8 }}>
              <Text style={s.sec}>Связаться</Text>
              {l.contacts.map((c) => (
                <Pressable key={c.type + c.url} onPress={() => open(c.url)} style={({ pressed }) => [s.contact, pressed && { opacity: 0.7 }]}>
                  {SOCIAL[c.type] ? <Image source={SOCIAL[c.type]} style={{ width: 30, height: 30 }} />
                    : <View style={s.ico}><MarketIcon name={c.type} color="#fff" size={16} /></View>}
                  <Text style={s.contactT}>{c.title}</Text>
                  <Text style={s.chev}>›</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          {!l.mine ? (
            <Pressable onPress={() => setSheet(true)} style={{ alignSelf: 'center', padding: 10 }}>
              <Text style={{ color: C.muted, fontWeight: '600' }}>Пожаловаться на объявление</Text>
            </Pressable>
          ) : null}
        </View>
      </ScrollView>
      <ActionSheet visible={sheet} onClose={() => setSheet(false)}
        actions={REPORT_REASONS.map(([key, title]) => ({ title, onPress: () => doReport(key) }))} />
    </>
  );
}

const s = StyleSheet.create({
  photo: { width: '100%', aspectRatio: 4 / 3, backgroundColor: C.line },
  price: { fontSize: 22, fontWeight: '800', color: C.accent },
  sec: { fontSize: 13, fontWeight: '700', color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8, marginLeft: 4 },
  contact: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: C.card, borderRadius: 18, borderWidth: 1, borderColor: C.line, paddingHorizontal: 14, paddingVertical: 12 },
  contactT: { flex: 1, fontSize: 16, fontWeight: '600', color: C.ink },
  ico: { width: 30, height: 30, borderRadius: 15, backgroundColor: C.ink, alignItems: 'center', justifyContent: 'center' },
  chev: { fontSize: 24, color: C.muted },
});
