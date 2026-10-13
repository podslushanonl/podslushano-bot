import { Image } from 'expo-image';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button, Card, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { SITE, TG_BOT, goUrl } from '@/lib/api';
import { useAuth } from '@/lib/auth';

const web = (path: string) => () => WebBrowser.openBrowserAsync(SITE + path);

const SECTIONS: { title: string; items: [string, string, () => void][] }[] = [
  { title: 'Сэкономить', items: [
    ['Медстраховка 2027', '6 вопросов и сравнение цен', () => Linking.openURL(`${TG_BOT}?start=save_zorg`)],
    ['eSIM для поездок', 'Интернет за границей без роуминга', web('/travel/')],
    ['Сравнить медстраховки', 'Цены на 2027 год', () => WebBrowser.openBrowserAsync(goUrl('zorg_compare'))],
  ] },
  { title: 'Сервисы', items: [
    ['Поезда NS', 'Отправления и сбои на железной дороге', () => router.push('/trains')],
    ['КонтактGuide', 'Русскоязычные специалисты', web('/guide/')],
    ['Работа и жильё', 'Объявления после модерации', web('/work/')],
    ['Погода и камеры', 'Buienradar и живые камеры', web('/live/')],
    ['Наш Telegram-бот', 'Разбор писем, налоги, предложка', () => Linking.openURL(TG_BOT)],
  ] },
  { title: 'Для бизнеса', items: [
    ['Добавить событие в афишу', '€9,99, на сайте и в боте', web('/events/')],
    ['Карточка в КонтактGuide', 'Для специалистов', web('/place/')],
    ['Реклама и сотрудничество', 'Instagram, Telegram, сайт', web('/business/')],
  ] },
  { title: 'podslushano', items: [
    ['Связаться с нами', 'Ответим за 5 рабочих дней', web('/contact/')],
    ['Конфиденциальность', '', web('/privacy-statement-eu/')],
    ['Условия', '', web('/terms-and-conditions/')],
  ] },
];

const SOCIAL: [any, string, string][] = [
  [require('@/assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@/assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@/assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@/assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

function Account() {
  const { user, favorites, ready } = useAuth();
  if (!ready) return null;
  if (!user) return (
    <Card style={{ backgroundColor: C.ink, borderColor: C.ink }}>
      <Eyebrow color="#FFB48E">Мой podslushano</Eyebrow>
      <H size={20}><Text style={{ color: '#fff' }}>Войдите, чтобы сохранять события</Text></H>
      <Text style={st.darkP}>Избранное, ваш город, чаты и объявления на барахолке. Пароль не нужен.</Text>
      <Button title="Войти или создать аккаунт" onPress={() => router.push('/login')} />
    </Card>
  );
  return (
    <Card style={{ backgroundColor: C.ink, borderColor: C.ink }}>
      <Eyebrow color="#FFB48E">Мой podslushano</Eyebrow>
      <H size={20}><Text style={{ color: '#fff' }}>{user.name ? `Привет, ${user.name}!` : 'Привет!'}</Text></H>
      <Text style={st.darkP}>{user.city ? `Ваш город: ${user.city}` : 'Укажите город в профиле'}</Text>
      {favorites.length ? (
        <View style={{ gap: 6, marginTop: 4 }}>
          <Text style={[st.darkP, { fontWeight: '700' }]}>Избранные события</Text>
          {favorites.slice(0, 5).map((f) => (
            <Pressable key={f.key} onPress={() => router.push({ pathname: '/event/[key]', params: { key: f.key } })}>
              <Text style={{ color: '#fff', fontSize: 15 }}>♥ {f.title || f.key}</Text>
            </Pressable>
          ))}
        </View>
      ) : <Text style={st.darkP}>Нажмите ♥ на событии в афише, чтобы сохранить его здесь.</Text>}
      <Button title="Профиль" soft onPress={() => router.push('/profile')} />
    </Card>
  );
}

export default function More() {
  return (
    <ScrollView contentContainerStyle={{ padding: 16, gap: 18, paddingBottom: 40 }}>
      <Account />
      {SECTIONS.map((sec) => (
        <View key={sec.title} style={{ gap: 8 }}>
          <Text style={st.sec}>{sec.title}</Text>
          <Card style={{ paddingVertical: 4, gap: 0 }}>
            {sec.items.map(([t, d, fn], i) => (
              <Pressable key={t} onPress={fn} style={({ pressed }) => [st.row, i > 0 && st.sep, pressed && { opacity: 0.6 }]}>
                <View style={{ flex: 1 }}>
                  <Text style={st.t}>{t}</Text>
                  {d ? <Text style={st.d}>{d}</Text> : null}
                </View>
                <Text style={st.chev}>›</Text>
              </Pressable>
            ))}
          </Card>
        </View>
      ))}
      <View style={st.social}>
        {SOCIAL.map(([img, name, url]) => (
          <Pressable key={name} onPress={() => Linking.openURL(url)} accessibilityLabel={name}>
            <Image source={img} style={{ width: 40, height: 40 }} />
          </Pressable>
        ))}
      </View>
      <P muted>podslushano.nl · жизнь в Нидерландах по-русски</P>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  sec: { fontSize: 13, fontWeight: '700', color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8, marginLeft: 4 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
  sep: { borderTopWidth: 1, borderTopColor: C.line },
  t: { fontSize: 16, fontWeight: '600', color: C.ink },
  d: { fontSize: 13, color: C.muted, marginTop: 2 },
  chev: { fontSize: 24, color: C.muted, marginLeft: 8 },
  social: { flexDirection: 'row', gap: 14, justifyContent: 'center', marginTop: 6 },
  darkP: { color: '#C9CED6', fontSize: 15, lineHeight: 21 },
});
