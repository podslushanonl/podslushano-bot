import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { logout, useAuth } from '@/api/auth';
import { SITE } from '@/api/client';
import { useMyListings } from '@/api/market';
import { useFriends } from '@/api/social';
import { prettyPhone } from '@/features/auth/phone';
import { CitySheet } from '@/features/common/CitySheet';
import { openBot, openUrl } from '@/lib/open';
import { useCity, useCountry } from '@/lib/useCity';
import { radius, useTheme } from '@/theme';
import { Button, Group, Icon, Img, PageScreen, Row, Tap, Txt, useToast } from '@/ui';

const SOCIAL: [any, string, string][] = [
  [require('@assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

export default function Settings() {
  const { c } = useTheme();
  const { user, favorites, ready } = useAuth();
  const [city, setCity] = useCity();
  const country = useCountry();
  const friends = useFriends(!!user);
  const [picker, setPicker] = useState(false);
  const mine = useMyListings(!!user);
  const toast = useToast();

  return (
    <PageScreen title="Настройки">
      <Txt v="title1">Настройки</Txt>
      {!ready ? null : user ? (
        <>
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
          <Txt v="callout" color={c.onHeroMuted}>Пароль не нужен: код по SMS или на почту, или вход через Telegram. Аккаунт создаётся сам.</Txt>
          <Button title="Войти или создать аккаунт" kind="accent" onPress={() => router.push('/login')} />
        </View>
      )}

      <Group title="Аккаунт">
        <Row first title="Мой город" sub={`${city}, ${country}`} icon="location" onPress={() => setPicker(true)} />
        {user ? <Row title="Друзья" sub={friends.data?.incoming.length ? `Заявок в друзья: ${friends.data.incoming.length}` : 'Найти людей, заявки'}
          icon="people" onPress={() => router.push('/friends')} /> : null}
        {user ? <Row title="Редактировать профиль" sub="Фото, имя, статус, страна" icon="person" onPress={() => router.push('/profile-edit')} /> : null}
        {user ? <Row title="Номер телефона" sub={user.phone ? prettyPhone(user.phone) : 'Привязать — вход по SMS'} icon="phone"
          onPress={() => router.push({ pathname: '/link', params: { kind: 'phone' } })} /> : null}
        {user ? <Row title="Почта" sub={user.email || 'Привязать — вход по коду из письма'} icon="mail"
          onPress={() => router.push({ pathname: '/link', params: { kind: 'email' } })} /> : null}
        {user ? <Row title="Мои объявления" sub={(() => { const n = (mine.data?.items || []).filter((l) => ['approved', 'pending', 'awaiting_payment'].includes(l.status || '')).length; return n ? `Активных: ${n}` : undefined; })()} icon="market" onPress={() => router.push('/market/my')} /> : null}
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
        <Txt v="footnote" center>podslushano.nl · Нидерланды изнутри</Txt>
      </View>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
    </PageScreen>
  );
}
