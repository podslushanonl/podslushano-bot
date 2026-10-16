import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { refreshMe, useAuth } from '@/api/auth';
import { startVerify, useVerifyStatus } from '@/api/billing';
import { routeForError } from '@/api/community';
import { dayMonth } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Button, handle, Icon, IconName, PageScreen, Txt, useToast, UserAvatar, VERIFIED_BLUE, VerifiedBadge } from '@/ui';

const BENEFITS: [IconName, string, string, string][] = [
  ['verified', VERIFIED_BLUE, 'Синяя галочка', 'Рядом с вашим @username в ленте, комментариях, чатах, историях и в профиле'],
  ['star', '#FF9F0A', 'Приоритет в ленте «Все»', 'Ваши свежие публикации — в самом начале рекомендаций для всех участников'],
  ['market', '#34C759', 'Доверие в Барахолке', 'Покупатели видят подтверждённого продавца и охотнее пишут'],
  ['creditcard', '#AF52DE', 'Без обязательств', 'Подписка 3,99 € в месяц, отменить можно в любой момент'],
];

function Benefit({ icon, bg, title, text }: { icon: IconName; bg: string; title: string; text: string }) {
  return (
    <View style={{ flexDirection: 'row', gap: 14, alignItems: 'center' }}>
      <View style={{ width: 42, height: 42, borderRadius: 21, backgroundColor: bg, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} filled size={20} color="#FFFFFF" />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="bodyStrong">{title}</Txt>
        <Txt v="footnote" tone="muted">{text}</Txt>
      </View>
    </View>
  );
}

/** «Премиум верификация»: синяя галочка за 3,99 € в месяц. Оплата — Stripe Checkout (страница оплаты),
 *  после оплаты галочка появляется везде сама (сервер получает подтверждение от Stripe). */
export default function Premium() {
  const { c } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const { paid, canceled } = useLocalSearchParams<{ paid?: string; canceled?: string }>();
  const st = useVerifyStatus(!!user);
  const [busy, setBusy] = useState(false);
  const s = st.data;
  // Вернулись со страницы оплаты Stripe: подтверждение приходит на сервер — обновляем статус и профиль
  const { refetch } = st;
  useEffect(() => {
    if (!paid) return;
    const t = setTimeout(() => { refetch(); refreshMe().catch(() => {}); }, 1500);
    return () => clearTimeout(t);
  }, [paid, refetch]);

  const buy = async () => {
    if (!user) { router.push('/login'); return; }
    setBusy(true);
    try {
      const d = await startVerify();
      if (d.paid) toast('Готово! Синяя галочка уже у вас');
      else if (d.url) {
        if (Platform.OS === 'web') (globalThis as any).location.assign(d.url); else openUrl(d.url);
      }
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };

  const price = `${(s?.price ?? 3.99).toFixed(2).replace('.', ',')} €`;
  const active = !!s?.verified;
  return (
    <PageScreen title="Премиум верификация"
      footer={!active ? (
        <Button title={s && !s.available ? 'Скоро' : `Подключить за ${price} в месяц`} kind="accent" icon="verified" loading={busy}
          disabled={!!s && !s.available} onPress={buy} />
      ) : undefined}>
      {/* Витрина: аватар с галочкой, как его увидят другие */}
      <View style={{ alignItems: 'center', gap: 10, paddingTop: 8 }}>
        <View style={{ width: 112, height: 112, borderRadius: 56, alignItems: 'center', justifyContent: 'center', backgroundColor: c.bgElevated,
          borderWidth: HAIRLINE, borderColor: c.line }}>
          {user ? <UserAvatar u={user} size={96} /> : <Icon name="verified" filled size={56} color={VERIFIED_BLUE} />}
          <View style={{ position: 'absolute', right: 4, bottom: 4, width: 34, height: 34, borderRadius: 17, backgroundColor: c.bg,
            alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="verified" filled size={28} color={VERIFIED_BLUE} />
          </View>
        </View>
        {user ? (
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Txt v="title3">{handle(user)}</Txt>
            <VerifiedBadge size={18} />
          </View>
        ) : null}
        <Txt v="title1" center>Премиум верификация</Txt>
        <Txt v="callout" tone="muted" center style={{ paddingHorizontal: 12 }}>
          Подтверждённый аккаунт заметнее в ленте и вызывает больше доверия у соседей и покупателей.
        </Txt>
      </View>

      {active ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16, borderRadius: radius.l, backgroundColor: c.accentSoft }}>
          <Icon name="verified" filled size={26} color={VERIFIED_BLUE} />
          <Txt v="bodyStrong" style={{ flex: 1 }}>
            {s?.lifetime ? 'У вас бессрочная галочка' : `Галочка активна до ${dayMonth(s?.until || '')}`}
          </Txt>
        </View>
      ) : (
        <View style={{ alignItems: 'center', gap: 2 }}>
          <Txt v="title1" style={{ fontSize: 40, lineHeight: 46 }}>{price}</Txt>
          <Txt v="subhead" tone="muted">в месяц · отмена в любой момент</Txt>
        </View>
      )}

      <View style={{ gap: 18, padding: 18, borderRadius: radius.l, backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line }}>
        {BENEFITS.map(([icon, bg, title, text]) => <Benefit key={title} icon={icon} bg={bg} title={title} text={text} />)}
      </View>

      {canceled ? <Txt v="callout" tone="muted" center>Оплата отменена — ничего не списано.</Txt> : null}
      {s && !s.available && !active ? (
        <Txt v="footnote" tone="muted" center>Подключение откроется совсем скоро — мы сообщим в приложении.</Txt>
      ) : (
        <Txt v="footnote" tone="muted" center>Оплата картой, Apple Pay или Google Pay через Stripe. Платёж защищён, данные карты мы не видим.</Txt>
      )}
    </PageScreen>
  );
}
