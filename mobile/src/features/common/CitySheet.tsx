import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { CITIES_BY_COUNTRY, Country } from '@/lib/countries';
import { CITIES } from '@/lib/useCity';
import { radius, useTheme } from '@/theme';
import { Glass, Icon, Tap, Txt } from '@/ui';

/** Выбор города снизу на стекле. */
export function CitySheet({ visible, value, onPick, onClose, extra = [], allLabel, country }: {
  visible: boolean; value: string; onPick: (c: string) => void; onClose: () => void; extra?: string[];
  /** Города этой страны; по умолчанию — Нидерланды. */
  country?: Country;
  /** Строка «все города» первой в списке (выбор — пустая строка). */
  allLabel?: string;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const list = [...(allLabel ? [''] : []), ...new Set([...extra.filter(Boolean), ...(country ? CITIES_BY_COUNTRY[country] : CITIES)])];
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable onPress={onClose} accessibilityLabel="Закрыть" style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end', padding: 10, paddingBottom: insets.bottom + 10 }}>
        <Pressable onPress={() => {}}>
          <Glass radius={radius.xl} strong style={{ maxHeight: 520 }}>
            <Txt v="headline" center style={{ paddingTop: 18, paddingBottom: 10 }}>{allLabel ? 'Город' : 'Ваш город'}</Txt>
            <ScrollView contentContainerStyle={{ paddingBottom: 8 }}>
              {list.map((city) => (
                <Tap key={city || 'all'} scaleTo={0.99} onPress={() => { onPick(city); onClose(); }}
                  style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 22, paddingVertical: 15, borderTopWidth: 1, borderTopColor: c.line }}>
                  <Txt v="bodyStrong" style={{ flex: 1 }}>{city || allLabel}</Txt>
                  {city === value ? <Icon name="check" size={18} color={c.accentText} /> : <View style={{ width: 18 }} />}
                </Tap>
              ))}
            </ScrollView>
          </Glass>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
