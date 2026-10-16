import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated';
import { logout, saveProfile, useAuth } from '@/api/auth';
import { SITE } from '@/api/client';
import { useMyListings } from '@/api/market';
import { useFriends } from '@/api/social';
import { prettyPhone } from '@/features/auth/phone';
import { CitySheet } from '@/features/common/CitySheet';
import { openBot, openUrl } from '@/lib/open';
import { RULE_SECTIONS } from '@/lib/rules';
import { useCity, useCountry } from '@/lib/useCity';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Avatar, Button, Group, Icon, Img, PageScreen, Row, Tap, Toggle, Txt, useToast, VerifiedBadge } from '@/ui';

// Цвета плашек — системная палитра iOS: у каждого пункта свой, белая иконка внутри
const C = { blue: '#007AFF', verified: '#1D9BF0', green: '#34C759', orange: '#FF9500', purple: '#AF52DE', indigo: '#5856D6',
  teal: '#30B0C7', pink: '#FF2D55', red: '#FF3B30', yellow: '#FFCC00', tg: '#2AABEE', gray: '#8E8E93', brand: '#FF6A1A' };
const RULE_COLORS = [C.brand, C.blue, C.green, C.purple, C.orange, C.teal, C.pink, C.indigo];

const SOCIAL: [any, string, string][] = [
  [require('@assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

/** Раскрывающийся раздел правил. */
function RuleSection({ s, first, color }: { s: (typeof RULE_SECTIONS)[number]; first: boolean; color: string }) {
  const { c } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <View style={{ borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <Tap onPress={() => setOpen(!open)} scaleTo={0.99} accessibilityState={{ expanded: open }} accessibilityLabel={s.title}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 13, minHeight: 56 }}>
        <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: color, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={s.icon} size={17} color="#FFFFFF" />
        </View>
        <Txt v="bodyStrong" style={{ flex: 1 }}>{s.title}</Txt>
        <View style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }}>
          <Icon name="down" thin size={16} color={c.muted} />
        </View>
      </Tap>
      {open ? (
        <Animated.View entering={FadeIn.duration(180)} exiting={FadeOut.duration(120)} style={{ paddingLeft: 62, paddingRight: 18, paddingBottom: 14, gap: 9 }}>
          {s.items.map((t) => (
            <View key={t} style={{ flexDirection: 'row', gap: 10 }}>
              <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: c.accent, marginTop: 9 }} />
              <Txt v="callout" tone="text" style={{ flex: 1 }}>{t}</Txt>
            </View>
          ))}
        </Animated.View>
      ) : null}
    </View>
  );
}

export default function Settings() {
  const { c } = useTheme();
  const { user, favorites, ready } = useAuth();
  const [city, setCity] = useCity();
  const country = useCountry();
  const friends = useFriends(!!user);
  const [picker, setPicker] = useState(false);
  const [saving, setSaving] = useState(false);
  const mine = useMyListings(!!user);
  const toast = useToast();
  const active = (mine.data?.items || []).filter((l) => l.status === 'active').length;

  const setPrivate = async (v: boolean) => {
    setSaving(true);
    try {
      await saveProfile({ is_private: v });
      toast(v ? 'Аккаунт закрыт: публикации видят только друзья' : 'Аккаунт открыт для всех');
    } catch (e: any) { toast(e?.message || 'Не сохранилось', 'error'); } finally { setSaving(false); }
  };

  return (
    <PageScreen title="Настройки">
      <Txt v="title1">Настройки</Txt>
      {!ready ? null : user ? (
        <Tap onPress={() => router.push('/profile-edit')} scaleTo={0.98} accessibilityLabel="Редактировать профиль"
          style={{ flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16, borderRadius: radius.l, backgroundColor: c.bgElevated,
            borderWidth: HAIRLINE, borderColor: c.line }}>
          <Avatar name={user.name} id={user.id} uri={user.avatar} size={58} />
          <View style={{ flex: 1, gap: 2 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Txt v="title3" numberOfLines={1} style={{ flexShrink: 1 }}>{user.name || 'Без имени'}</Txt>
              {user.verified ? <VerifiedBadge size={18} /> : null}
            </View>
            {user.username ? <Txt v="subhead" tone="ink" numberOfLines={1}>@{user.username}</Txt> : null}
            <Txt v="footnote" tone="muted" numberOfLines={1}>{user.phone ? prettyPhone(user.phone) : user.email || 'Фото, имя, статус'}</Txt>
          </View>
          <Txt v="subhead" tone="accent" style={{ fontFamily: 'Onest_600SemiBold' }}>Изменить</Txt>
        </Tap>
      ) : (
        <View style={{ backgroundColor: c.hero, borderRadius: radius.xxl, borderWidth: HAIRLINE, borderColor: c.line, padding: 22, gap: 12 }}>
          <Txt v="overline" color={c.accent}>Мой podslushano</Txt>
          <Txt v="title2" color={c.onHero}>Один аккаунт — объявления, сообщения и избранное</Txt>
          <Txt v="callout" color={c.onHeroMuted}>Пароль не нужен: код по SMS или на почту. Аккаунт создаётся сам.</Txt>
          <Button title="Войти или создать аккаунт" kind="accent" onPress={() => router.push('/login')} />
        </View>
      )}

      {user ? (
        <Group title="Аккаунт">
          <Row first title="Премиум верификация" icon="verified" iconBg={C.verified}
            sub={user.verified ? 'Синяя галочка активна' : 'Синяя галочка · 3,99 € в месяц'} onPress={() => router.push('/premium')} />
          <Row title="Номер телефона" sub={user.phone ? prettyPhone(user.phone) : 'Привязать — вход по SMS'} icon="phone" iconBg={C.green}
            onPress={() => router.push({ pathname: '/link', params: { kind: 'phone' } })} />
          <Row title="Почта" sub={user.email || 'Привязать — вход по коду из письма'} icon="mail" iconBg={C.blue}
            onPress={() => router.push({ pathname: '/link', params: { kind: 'email' } })} />
          <Row title="Моё место" icon="location" iconBg={C.orange} onPress={() => setPicker(true)}
            sub={city ? `${city}, ${country}${user.located ? ' · по GPS' : ''}` : 'Определить по GPS или выбрать'} />
          <Row title="Друзья" sub={friends.data?.incoming.length ? `Заявок в друзья: ${friends.data.incoming.length}` : 'Найти людей, заявки, блокировки'}
            icon="people" iconBg={C.purple} onPress={() => router.push('/friends')} />
        </Group>
      ) : (
        <Group title="Место">
          <Row first title="Мой город" sub={city ? `${city}, ${country}` : 'Выбрать'} icon="location" iconBg={C.orange} onPress={() => setPicker(true)} />
        </Group>
      )}

      {user ? (
        <Group title="Конфиденциальность">
          <Row first title="Закрытый аккаунт" icon="lock" iconBg={C.indigo} chevron={false}
            sub={user.is_private ? 'Публикации и друзей видят только друзья' : 'Публикации видят все участники'}
            right={<Toggle value={!!user.is_private} onChange={setPrivate} disabled={saving} label="Закрытый аккаунт" />} />
        </Group>
      ) : null}

      {user ? (
        <Group title="Безопасность">
          <Row first title="Активные сессии" sub="Устройства, на которых выполнен вход" icon="devices" iconBg={C.teal} onPress={() => router.push('/sessions')} />
          <Row title="Вход по SMS и почте" sub="Пароль не нужен — одноразовый код" icon="shield" iconBg={C.green} chevron={false} />
        </Group>
      ) : null}

      {user ? (
        <Group title="Мои разделы">
          <Row first title="Мои объявления" sub={active ? `Активных: ${active}` : 'Барахолка'} icon="market" iconBg={C.green} onPress={() => router.push('/market/my')} />
          {favorites.filter((f) => f.kind !== 'listing').slice(0, 8).map((f) => (
            <Row key={f.kind + f.key} title={f.title || f.key}
              sub={f.kind === 'item' ? 'Избранное · Барахолка' : f.kind === 'post' ? 'Закладки · Публикация' : 'Избранное · Афиша'}
              icon={f.kind === 'item' ? 'heart' : f.kind === 'post' ? 'bookmarkFill' : 'ticket'}
              iconBg={f.kind === 'item' ? C.pink : f.kind === 'post' ? C.yellow : C.brand}
              onPress={() => (f.kind === 'item'
                ? router.push({ pathname: '/market/[id]', params: { id: f.key } })
                : f.kind === 'post' ? router.push({ pathname: '/post/[id]', params: { id: f.key } })
                : router.push({ pathname: '/event/[key]', params: { key: f.key } }))} />
          ))}
        </Group>
      ) : null}

      <Group title="Правила сообщества">
        {RULE_SECTIONS.map((s, i) => <RuleSection key={s.title} s={s} first={i === 0} color={RULE_COLORS[i % RULE_COLORS.length]} />)}
      </Group>

      <Group title="podslushano">
        <Row first title="Связаться с нами" sub="Ответим за 5 рабочих дней" icon="mail" iconBg={C.blue} onPress={() => openUrl(`${SITE}/contact/`)} />
        <Row title="Реклама и сотрудничество" icon="sparkles" iconBg={C.orange} onPress={() => openUrl(`${SITE}/business/`)} />
        <Row title="Наш Telegram-бот" sub="Новости и полезные подборки" icon="bubble" iconBg={C.tg} onPress={() => openBot()} />
        <Row title="Политика конфиденциальности" icon="shield" iconBg={C.gray} onPress={() => openUrl(`${SITE}/privacy-statement-eu/`)} />
        <Row title="Условия" icon="info" iconBg={C.gray} onPress={() => openUrl(`${SITE}/terms-and-conditions/`)} />
      </Group>

      {user ? (
        <Group>
          <Row first title="Выйти" icon="logout" iconBg={C.red} danger chevron={false} onPress={() => logout().then(() => toast('Вы вышли из аккаунта'))} />
        </Group>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 14, justifyContent: 'center' }}>
        {SOCIAL.map(([img, name, url]) => (
          <Tap key={name} onPress={() => openUrl(url)} scaleTo={0.88} accessibilityLabel={name} accessibilityRole="link">
            <Img source={img} style={{ width: 42, height: 42, backgroundColor: 'transparent' }} />
          </Tap>
        ))}
      </View>
      <Txt v="footnote" center>podslushano.nl · Нидерланды изнутри</Txt>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
    </PageScreen>
  );
}
