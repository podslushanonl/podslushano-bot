import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';
import { AppSession, endSessions, listSessions } from '@/api/auth';
import { timeLabel } from '@/features/feed/cards';
import { useTheme } from '@/theme';
import { ActionSheet, Button, Group, IconName, PageScreen, Row, Skeleton, Txt, useToast } from '@/ui';

const deviceIcon = (d: string): IconName => (/iPhone|Android|iPad/.test(d) ? 'phone' : 'devices');

/** Активные сессии: где выполнен вход, завершить один сеанс или все, кроме этого устройства. */
export default function Sessions() {
  const { c } = useTheme();
  const toast = useToast();
  const q = useQuery({ queryKey: ['me', 'sessions'], queryFn: listSessions });
  const [pick, setPick] = useState<AppSession | null>(null);
  const [busy, setBusy] = useState(false);
  const items = q.data?.items || [];
  const current = items.find((s) => s.current);
  const others = items.filter((s) => !s.current);

  const end = async (p: { id: string } | { others: true }, ok: string) => {
    setBusy(true);
    try { await endSessions(p); toast(ok); q.refetch(); } catch (e: any) { toast(e?.message || 'Не получилось', 'error'); } finally { setBusy(false); }
  };
  const sub = (s: AppSession) => [s.current ? 'Это устройство' : `В сети: ${timeLabel(s.last_seen)}`, s.ip].filter(Boolean).join(' · ');

  return (
    <PageScreen title="Активные сессии" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <View style={{ gap: 6 }}>
        <Txt v="title1">Активные сессии</Txt>
        <Txt v="callout" tone="muted">Устройства, на которых выполнен вход в ваш аккаунт. Не узнаёте устройство — завершите сеанс.</Txt>
      </View>
      {q.isLoading ? <Skeleton h={140} r={16} /> : (
        <>
          <Group title="Это устройство">
            {current ? <Row first title={current.device} sub={sub(current)} icon={deviceIcon(current.device)} iconBg={c.accent} />
              : <Row first title="Это устройство" sub="Вход выполнен до появления списка сеансов" icon="phone" iconBg={c.accent} />}
          </Group>
          {others.length ? (
            <Group title={`Другие устройства · ${others.length}`}>
              {others.map((s, i) => <Row key={s.id} first={i === 0} title={s.device} sub={sub(s)} icon={deviceIcon(s.device)} onPress={() => setPick(s)} />)}
            </Group>
          ) : <Txt v="footnote" tone="muted" style={{ marginLeft: 6 }}>Других устройств с открытым входом нет.</Txt>}
          <Button title="Завершить все другие сеансы" kind="danger" icon="logout" loading={busy}
            disabled={!others.length && !q.data?.legacy}
            onPress={() => end({ others: true }, 'Другие сеансы завершены')} />
          <Txt v="footnote" tone="muted">На завершённых устройствах нужно будет войти заново по коду.</Txt>
        </>
      )}
      <ActionSheet visible={!!pick} title={pick?.device} onClose={() => setPick(null)}
        actions={pick ? [{ title: 'Завершить сеанс', icon: 'logout', danger: true, onPress: () => end({ id: pick.id }, 'Сеанс завершён') }] : []} />
    </PageScreen>
  );
}
