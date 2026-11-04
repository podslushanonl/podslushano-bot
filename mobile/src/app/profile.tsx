import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, View } from 'react-native';
import { logout, useAuth } from '@/api/auth';
import { SITE } from '@/api/client';
import { prettyPhone } from '@/features/auth/phone';
import { openUrl } from '@/lib/open';
import { useProvince } from '@/lib/province';
import { disablePush, enablePush, PushError, pushSupported, usePushEnabled } from '@/lib/push';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Avatar, Button, Group, Img, PageScreen, Row, Tap, Toggle, Txt, useToast } from '@/ui';

const SOCIAL: [any, string, string][] = [
  [require('@assets/images/social/instagram.png'), 'Instagram', 'https://www.instagram.com/podslushano.nl'],
  [require('@assets/images/social/telegram.png'), 'Telegram', 'https://t.me/podslushanovnl'],
  [require('@assets/images/social/facebook.png'), 'Facebook', 'https://www.facebook.com/podslushano.nl'],
  [require('@assets/images/social/tiktok.png'), 'TikTok', 'https://www.tiktok.com/@podslushano.nl'],
];

/** Профиль: аккаунт, провинция, избранное, безопасность и всё о приложении. Открывается из шапки любого раздела. */
export default function Profile() {
  const { c } = useTheme();
  const toast = useToast();
  const { user, favorites, ready } = useAuth();
  const { province } = useProvince();
  const events = favorites.filter((f) => f.kind === 'event');
  const pushOn = usePushEnabled();
  const [pushBusy, setPushBusy] = useState(false);
  const togglePush = async (v: boolean) => {
    setPushBusy(true);
    try {
      if (v) { await enablePush(province!.id); toast(`Уведомления включены: ${province!.name}`); } else { await disablePush(); toast('Уведомления выключены'); }
    } catch (e) {
      toast(e instanceof PushError ? e.message : 'Не получилось включить уведомления. Попробуйте ещё раз.', 'error');
    } finally { setPushBusy(false); }
  };

  return (
    <PageScreen title="Профиль">
      <Txt v="title1" accessibilityRole="header">Профиль</Txt>

      {!ready ? null : user ? (
        <Tap onPress={() => router.push('/profile-edit')} scaleTo={0.98} accessibilityLabel="Изменить имя и фото"
          style={{ flexDirection: 'row', alignItems: 'center', gap: 14, padding: 16, borderRadius: radius.l, backgroundColor: c.bgElevated,
            borderWidth: HAIRLINE, borderColor: c.line }}>
          <Avatar name={user.name || 'Я'} id={user.id} uri={user.avatar} size={58} />
          <View style={{ flex: 1, gap: 2 }}>
            <Txt v="title3" numberOfLines={1}>{user.name || 'Без имени'}</Txt>
            <Txt v="footnote" numberOfLines={1}>{user.phone ? prettyPhone(user.phone) : user.email}</Txt>
          </View>
          <Txt v="subhead" tone="accent" style={{ fontFamily: 'Onest_600SemiBold' }}>Изменить</Txt>
        </Tap>
      ) : (
        <View style={{ backgroundColor: c.bgElevated, borderRadius: radius.xl, borderWidth: HAIRLINE, borderColor: c.line, padding: 20, gap: 12 }}>
          <Txt v="title2">Войдите, чтобы сохранять избранное</Txt>
          <Txt v="callout" tone="muted">Пароль не нужен: код придёт по SMS или на почту. Аккаунт создаётся автоматически.</Txt>
          <Button title="Войти или создать аккаунт" kind="accent" onPress={() => router.push('/login')} />
        </View>
      )}

      <Group title="Провинция">
        <Row first icon="location" iconBg={c.accent} title={province?.name || 'Не выбрана'} sub="Афиша, места и контакт-гайд — из этой провинции"
          onPress={() => router.push('/province')} />
        {pushSupported ? (
          <Row icon="bell" title="Уведомления" sub={pushOn ? 'Новые события и важное в вашей провинции' : 'Выключены'} chevron={false}
            right={<Toggle value={pushOn} onChange={togglePush} disabled={pushBusy || !province} label="Уведомления" />} />
        ) : null}
      </Group>

      {user ? (
        <>
          <Group title="Вход в аккаунт">
            <Row first icon="phone" title="Телефон" sub={user.phone ? prettyPhone(user.phone) : 'Добавить для входа по SMS'}
              onPress={() => router.push({ pathname: '/link', params: { kind: 'phone' } })} />
            <Row icon="mail" title="Почта" sub={user.email || 'Добавить для входа по коду из письма'}
              onPress={() => router.push({ pathname: '/link', params: { kind: 'email' } })} />
            <Row icon="devices" title="Активные сеансы" sub="Устройства, на которых выполнен вход" onPress={() => router.push('/sessions')} />
          </Group>
          {events.length ? (
            <Group title="Избранные события">
              {events.slice(0, 10).map((f, i) => (
                <Row key={f.key} first={i === 0} icon="ticket" title={f.title || 'Событие'}
                  onPress={() => router.push({ pathname: '/event/[key]', params: { key: f.key } })} />
              ))}
            </Group>
          ) : null}
        </>
      ) : null}

      <Group title="podslushano.nl">
        <Row first icon="mail" title="Связаться с нами" sub="Ответим в течение 5 рабочих дней" onPress={() => openUrl(`${SITE}/contact/`)} />
        <Row icon="briefcase" title="Реклама и сотрудничество" onPress={() => openUrl(`${SITE}/business/`)} />
        {/* Пожертвования через внешнюю оплату Apple и Google разрешают только некоммерческим организациям,
            поэтому в сборках для магазинов приложений этого пункта нет, только в веб-версии */}
        {Platform.OS === 'web' ? (
          <Row icon="heart" title="Вклад в развитие" sub="Помогает оплачивать сервисы и контент"
            onPress={() => openUrl('https://payment-links.mollie.com/payment/dTrV8jR8mFbe6iB2DWgtf')} />
        ) : null}
        <Row icon="shield" title="Политика конфиденциальности" onPress={() => openUrl(`${SITE}/privacy-app/`)} />
        <Row icon="info" title="Условия использования" onPress={() => openUrl(`${SITE}/terms-and-conditions/`)} />
      </Group>

      {user ? (
        <Group>
          <Row first icon="logout" title="Выйти" danger chevron={false} onPress={() => logout().then(() => toast('Вы вышли из аккаунта'))} />
          <Row icon="trash" title="Удалить аккаунт" sub="Данные и публикации удалятся навсегда" danger onPress={() => router.push('/delete-account')} />
        </Group>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 14, justifyContent: 'center' }}>
        {SOCIAL.map(([img, name, url]) => (
          <Tap key={name} onPress={() => openUrl(url)} scaleTo={0.88} accessibilityLabel={name} accessibilityRole="link">
            <Img source={img} style={{ width: 42, height: 42, backgroundColor: 'transparent' }} />
          </Tap>
        ))}
      </View>
      <Txt v="caption" center selectable>
        podslushano.nl · KVK 98882317 · BTW NL005359099B74{'\n'}Karel Doormanstraat 63, 5342 TJ Oss · podslushano.nl@gmail.com
      </Txt>
    </PageScreen>
  );
}
