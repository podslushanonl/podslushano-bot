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

const SOCIAL: [any, string, string][] = [
  [require('@assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

/** Раскрывающийся раздел правил. */
function RuleSection({ s, first }: { s: (typeof RULE_SECTIONS)[number]; first: boolean }) {
  const { c } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <View style={{ borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <Tap onPress={() => setOpen(!open)} scaleTo={0.99} accessibilityState={{ expanded: open }} accessibilityLabel={s.title}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 13, minHeight: 56 }}>
        <View style={{ width: 34, height: 34, borderRadius: 10, backgroundColor: open ? c.accentSoft : c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={s.icon} size={18} color={open ? c.accent : c.ink} />
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
          <Row first title="Номер телефона" sub={user.phone ? prettyPhone(user.phone) : 'Привязать — вход по SMS'} icon="phone"
            onPress={() => router.push({ pathname: '/link', params: { kind: 'phone' } })} />
          <Row title="Почта" sub={user.email || 'Привязать — вход по коду из письма'} icon="mail"
            onPress={() => router.push({ pathname: '/link', params: { kind: 'email' } })} />
          <Row title="Мой город" sub={`${city}, ${country}`} icon="location" onPress={() => setPicker(true)} />
          <Row title="Друзья" sub={friends.data?.incoming.length ? `Заявок в друзья: ${friends.data.incoming.length}` : 'Найти людей, заявки, блокировки'}
            icon="people" onPress={() => router.push('/friends')} />
        </Group>
      ) : (
        <Group title="Город">
          <Row first title="Мой город" sub={`${city}, ${country}`} icon="location" onPress={() => setPicker(true)} />
        </Group>
      )}

      {user ? (
        <Group title="Конфиденциальность">
          <Row first title="Закрытый аккаунт" icon="lock" chevron={false}
            sub={user.is_private ? 'Публикации и друзей видят только друзья' : 'Публикации видят все участники'}
            right={<Toggle value={!!user.is_private} onChange={setPrivate} disabled={saving} label="Закрытый аккаунт" />} />
          <Row title="Активные сессии" sub="Устройства, на которых выполнен вход" icon="devices" onPress={() => router.push('/sessions')} />
        </Group>
      ) : null}

      {user ? (
        <Group title="Мои разделы">
          <Row first title="Мои объявления" sub={active ? `Активных: ${active}` : 'Барахолка'} icon="market" onPress={() => router.push('/market/my')} />
          {favorites.filter((f) => f.kind !== 'listing').slice(0, 6).map((f) => (
            <Row key={f.kind + f.key} title={f.title || f.key} sub={f.kind === 'item' ? 'Избранное · Барахолка' : 'Избранное · Афиша'}
              icon={f.kind === 'item' ? 'heart' : 'ticket'}
              onPress={() => (f.kind === 'item'
                ? router.push({ pathname: '/market/[id]', params: { id: f.key } })
                : router.push({ pathname: '/event/[key]', params: { key: f.key } }))} />
          ))}
        </Group>
      ) : null}

      <Group title="Правила сообщества">
        {RULE_SECTIONS.map((s, i) => <RuleSection key={s.title} s={s} first={i === 0} />)}
      </Group>

      <Group title="podslushano">
        <Row first title="Связаться с нами" sub="Ответим за 5 рабочих дней" icon="mail" onPress={() => openUrl(`${SITE}/contact/`)} />
        <Row title="Реклама и сотрудничество" icon="sparkles" onPress={() => openUrl(`${SITE}/business/`)} />
        <Row title="Наш Telegram-бот" sub="Новости и полезные подборки" icon="bubble" onPress={() => openBot()} />
        <Row title="Политика конфиденциальности" icon="shield" onPress={() => openUrl(`${SITE}/privacy-statement-eu/`)} />
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
      <Txt v="footnote" center>podslushano.nl · Нидерланды изнутри</Txt>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
    </PageScreen>
  );
}
