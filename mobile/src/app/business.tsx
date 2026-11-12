import { router } from 'expo-router';
import { View } from 'react-native';
import { dayMonth } from '@/lib/format';
import { BusinessItem, MOCK_BUSINESS } from '@/mocks';
import { HAIRLINE, radius, space, useTheme } from '@/theme';
import { Button, Icon, LargeTitle, PageScreen, Txt } from '@/ui';

const STATUS: Record<BusinessItem['status'], { label: string; tone: 'success' | 'accent' | 'muted' }> = {
  active: { label: 'Опубликовано', tone: 'success' }, pending: { label: 'Ждёт оплаты', tone: 'accent' }, draft: { label: 'Черновик', tone: 'muted' },
};

/** Кабинет бизнеса: платные размещения, статус оплаты, просмотры и клики. Данные тестовые до этапа 5. */
export default function Business() {
  const { c } = useTheme();
  return (
    <PageScreen title="Кабинет бизнеса">
      <LargeTitle title="Кабинет бизнеса" sub="Ваши события и карточки специалиста" />
      <View style={{ padding: 12, borderRadius: radius.control, backgroundColor: c.secondarySoft }}>
        <Txt v="footnote" color={c.secondary}>Пример: здесь показаны тестовые размещения. Настоящие появятся после подключения оплаты (этап 5).</Txt>
      </View>
      {MOCK_BUSINESS.map((b) => {
        const st = STATUS[b.status];
        const color = st.tone === 'success' ? c.success : st.tone === 'accent' ? c.accentText : c.muted;
        return (
          <View key={b.id} style={{ backgroundColor: c.bgElevated, borderRadius: radius.card, borderWidth: HAIRLINE, borderColor: c.line, padding: 16, gap: 12 }}>
            <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12 }}>
              <View style={{ width: 40, height: 40, borderRadius: radius.control, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                <Icon name={b.kind === 'event' ? 'ticket' : 'people'} size={20} color={c.accentText} />
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Txt v="overline" color={color}>{st.label}{b.until ? ` · до ${dayMonth(b.until)}` : ''}</Txt>
                <Txt v="headline">{b.title}</Txt>
                <Txt v="footnote" tone="muted">{b.kind === 'event' ? 'Событие в Афише' : 'Карточка в КонтактGuide'}</Txt>
              </View>
            </View>
            {b.status === 'active' ? (
              <View style={{ flexDirection: 'row', gap: space.gap }}>
                {[['Просмотры', b.views], ['Клики', b.clicks]].map(([k, v]) => (
                  <View key={k} style={{ flex: 1, padding: 12, borderRadius: radius.control, backgroundColor: c.bg }}>
                    <Txt v="title2">{v}</Txt>
                    <Txt v="footnote" tone="muted">{k}</Txt>
                  </View>
                ))}
              </View>
            ) : (
              <Button kind={b.status === 'pending' ? 'accent' : 'secondary'} size="s" title={b.status === 'pending' ? 'Оплатить €9,99' : 'Продолжить заполнение'}
                onPress={() => router.push({ pathname: '/create/[kind]', params: { kind: b.kind } })} />
            )}
          </View>
        );
      })}
      <Button kind="secondary" icon="plus" title="Добавить событие" onPress={() => router.push({ pathname: '/create/[kind]', params: { kind: 'event' } })} />
      <Button kind="secondary" icon="plus" title="Разместить карточку специалиста" onPress={() => router.push({ pathname: '/create/[kind]', params: { kind: 'card' } })} />
    </PageScreen>
  );
}
