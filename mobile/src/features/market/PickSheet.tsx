import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { radius, useTheme } from '@/theme';
import { Glass, Icon, IconName, Tap, Txt } from '@/ui';

export type PickOption = { key: string; title: string; hint?: string; icon?: IconName };

/** Выпадающий список снизу (как системный Picker): строки с иконкой, подсказкой и галочкой у выбранной. */
export function PickSheet({ visible, title, options, value, onPick, onClose }: {
  visible: boolean; title: string; options: PickOption[]; value: string; onPick: (key: string) => void; onClose: () => void;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable onPress={onClose} accessibilityLabel="Закрыть"
        style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end', padding: 10, paddingBottom: insets.bottom + 10 }}>
        <Pressable onPress={() => {}}>
          <Glass radius={radius.xl} strong style={{ maxHeight: 560 }}>
            <Txt v="headline" center style={{ paddingTop: 18, paddingBottom: 10 }}>{title}</Txt>
            <ScrollView contentContainerStyle={{ paddingBottom: 6 }}>
              {options.map((o) => {
                const on = o.key === value;
                return (
                  <Tap key={o.key} scaleTo={0.99} onPress={() => { onPick(o.key); onClose(); }} accessibilityState={{ selected: on }}
                    style={{ flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingVertical: o.hint ? 12 : 15,
                      borderTopWidth: 1, borderTopColor: c.line }}>
                    {o.icon ? (
                      <View style={{ width: 40, height: 40, borderRadius: 13, alignItems: 'center', justifyContent: 'center',
                        backgroundColor: on ? c.accentSoft : c.bgSunken }}>
                        <Icon name={o.icon} thin size={21} color={on ? c.accent : c.ink} />
                      </View>
                    ) : null}
                    <View style={{ flex: 1, gap: 1 }}>
                      <Txt v="bodyStrong">{o.title}</Txt>
                      {o.hint ? <Txt v="footnote" tone="muted">{o.hint}</Txt> : null}
                    </View>
                    {on ? <Icon name="check" size={18} color={c.accent} /> : <View style={{ width: 18 }} />}
                  </Tap>
                );
              })}
            </ScrollView>
          </Glass>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
