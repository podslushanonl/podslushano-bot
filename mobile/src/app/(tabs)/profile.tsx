import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { logout, useAuth } from '@/api/auth';
import { SITE } from '@/api/client';
import { useMyListings } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { openBot, openUrl } from '@/lib/open';
import { useCity } from '@/lib/useCity';
import { radius, useTheme } from '@/theme';
import { Avatar, Button, Group, Icon, Img, Row, TabScreen, Tap, Txt, useToast } from '@/ui';

const SOCIAL: [any, string, string][] = [
  [require('@assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

function Stat({ n, label, onPress }: { n: number | string; label: string; onPress: () => void }) {
  const { c } = useTheme();
  return (
    <Tap onPress={onPress} scaleTo={0.96} style={{ flex: 1, backgroundColor: c.bgElevated, borderRadius: radius.l, padding: 14, gap: 2, borderWidth: 1, borderColor: c.line }}>
      <Txt v="title1" style={{ fontSize: 24, lineHeight: 29 }}>{n}</Txt>
      <Txt v="footnote">{label}</Txt>
    </Tap>
  );
}

export default function Profile() {
  const { c } = useTheme();
  const { user, favorites, ready } = useAuth();
  const [city, setCity] = useCity();
  const [picker, setPicker] = useState(false);
  const mine = useMyListings(!!user);
  const toast = useToast();
  const active = (mine.data?.items || []).filter((l) => ['approved', 'pending', 'awaiting_payment'].includes(l.status || '')).length;

  return (
    <TabScreen title="Профиль">
      {!ready ? null : user ? (
        <>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
            <Avatar name={user.name || user.email} id={user.id} size={72} />
            <View style={{ flex: 1, gap: 3 }}>
              <Txt v="title2">{user.name || 'Без имени'}</Txt>
              <Txt v="subhead" tone="muted" numberOfLines={1}>{[user.city, user.email || (user.telegram ? 'через Telegram' : '')].filter(Boolean).join(' · ')}</Txt>
            </View>
            <Button title="Изменить" kind="secondary" size="s" full={false} onPress={() => router.push('/profile-edit')} />
          </View>
          <View style={{ flexDirection: 'row', gap: 10 }}>
            <Stat n={active} label="объявления" onPress={() => router.push('/market/my')} />
            <Stat n={favorites.length} label="в избранном" onPress={() => router.push('/market')} />
          </View>
          {favorites.length ? (
            <Group title="Избранное">
              {favorites.slice(0, 8).map((f, i) => (
                <Row key={f.kind + f.key} first={i === 0} title={f.title || f.key} sub={f.kind === 'listing' ? 'Барахолка' : 'Афиша'}
                  icon={f.kind === 'listing' ? 'market' : 'ticket'} iconBg={c.accent}
                  onPress={() => (f.kind === 'listing'
                    ? router.push({ pathname: '/market/[id]', params: { id: f.key } })
                    : router.push({ pathname: '/event/[key]', params: { key: f.key } }))} />
              ))}
            </Group>
          ) : null}
        </>
      ) : (
        <View style={{ backgroundColor: c.hero, borderRadius: radius.xxl, padding: 22, gap: 12 }}>
          <Txt v="overline" color={c.accent}>Мой podslushano</Txt>
          <Txt v="title2" color={c.onHero}>Один аккаунт — объявления, сообщения и избранное</Txt>
          <Txt v="callout" color={c.onHeroMuted}>Пароль не нужен: код на почту или вход через Telegram. Аккаунт создаётся сам.</Txt>
          <Button title="Войти или создать аккаунт" kind="accent" onPress={() => router.push('/login')} />
        </View>
      )}

      <Group title="Настройки">
        <Row first title="Мой город" sub={city} icon="location" onPress={() => setPicker(true)} />
        {user ? <Row title="Мои объявления" icon="market" onPress={() => router.push('/market/my')} /> : null}
        <Row title="Правила сообщества" icon="shield" onPress={() => router.push('/rules')} />
      </Group>

      <Group title="podslushano">
        <Row first title="Наш Telegram-бот" sub="Разбор писем, налоги, предложка" icon="bubble" onPress={() => openBot()} />
        <Row title="Связаться с нами" sub="Ответим за 5 рабочих дней" icon="mail" onPress={() => openUrl(`${SITE}/contact/`)} />
        <Row title="Реклама и сотрудничество" icon="sparkles" onPress={() => openUrl(`${SITE}/business/`)} />
        <Row title="Конфиденциальность" icon="lock" onPress={() => openUrl(`${SITE}/privacy-statement-eu/`)} />
        <Row title="Условия" icon="info" onPress={() => openUrl(`${SITE}/terms-and-conditions/`)} />
      </Group>

      {user ? (
        <Group>
          <Row first title="Выйти" icon="logout" danger chevron={false} onPress={() => logout().then(() => toast('Вы вышли из аккаунта'))} />
        </Group>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 14, justifyContent: 'center' }}>
        {SOCIAL.map(([img, name, url]) => (
          <Tap key={name} onPress={() => openUrl(url)} scaleTo={0.88} accessibilityLabel={name} accessibilityRole="link">
            <Img source={img} style={{ width: 42, height: 42, backgroundColor: 'transparent' }} />
          </Tap>
        ))}
      </View>
      <View style={{ alignItems: 'center', gap: 4 }}>
        <Icon name="sparkles" size={16} color={c.faint} />
        <Txt v="footnote" center>podslushano.nl · жизнь в Нидерландах по-русски</Txt>
      </View>
      <CitySheet visible={picker} value={city} onPick={setCity} onClose={() => setPicker(false)} />
    </TabScreen>
  );
}
