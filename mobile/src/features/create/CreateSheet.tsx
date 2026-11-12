import { router } from 'expo-router';
import { View } from 'react-native';
import { HAIRLINE, radius, TOUCH, useTheme } from '@/theme';
import { BottomSheetWrapper, Icon, IconName, Tap, Txt } from '@/ui';

export type CreateKind = 'event' | 'card' | 'suggest';
export const CREATE: { kind: CreateKind; icon: IconName; title: string; sub: string; price?: string }[] = [
  { kind: 'event', icon: 'ticket', title: 'Добавить событие в Афишу', sub: 'Концерт, встреча, мастер-класс: увидят все, кто ищет, куда сходить', price: '€9,99' },
  { kind: 'card', icon: 'people', title: 'Разместить карточку в КонтактGuide', sub: 'Для специалистов и бизнеса: клиенты пишут вам в один тап', price: '€9,99' },
  { kind: 'suggest', icon: 'newspaper', title: 'Предложить новость или вопрос', sub: 'Расскажите редакции, что происходит рядом с вами' },
];

/** Шторка центральной кнопки «+»: что можно добавить в приложение. */
export function CreateSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { c } = useTheme();
  return (
    <BottomSheetWrapper visible={visible} onClose={onClose} title="Что добавить?">
      {CREATE.map((o) => (
        <Tap key={o.kind} haptic="light" scaleTo={0.98} accessibilityLabel={`${o.title}${o.price ? `, ${o.price}` : ', бесплатно'}`}
          onPress={() => { onClose(); router.push({ pathname: '/create/[kind]', params: { kind: o.kind } }); }}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: TOUCH, padding: 14, borderRadius: radius.card,
            backgroundColor: c.bg, borderWidth: HAIRLINE, borderColor: c.line }}>
          <View style={{ width: 44, height: 44, borderRadius: radius.control, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name={o.icon} size={22} color={c.accentText} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Txt v="headline">{o.title}</Txt>
            <Txt v="footnote" tone="muted">{o.sub}</Txt>
          </View>
          <View style={{ paddingHorizontal: 10, height: 26, borderRadius: radius.pill, justifyContent: 'center',
            backgroundColor: o.price ? c.accent : c.secondarySoft }}>
            <Txt v="caption" color={o.price ? c.onAccent : c.secondary} style={{ fontWeight: '700' }}>{o.price || 'Бесплатно'}</Txt>
          </View>
        </Tap>
      ))}
      <Txt v="footnote" tone="muted" center>Оплата через iDEAL (Mollie). Размещение проверяет редакция.</Txt>
    </BottomSheetWrapper>
  );
}
