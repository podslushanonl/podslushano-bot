import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { C } from '@/constants/theme';

export type SheetAction = { title: string; danger?: boolean; onPress: () => void };

/** Простое меню действий снизу (одинаково на iOS, Android и в браузере). */
export function ActionSheet({ visible, actions, onClose }: { visible: boolean; actions: SheetAction[]; onClose: () => void }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose}>
        <View style={s.sheet}>
          {actions.map((a, i) => (
            <Pressable key={a.title} onPress={() => { onClose(); a.onPress(); }} style={[s.row, i > 0 && s.sep]}>
              <Text style={[s.t, a.danger && { color: C.warn }]}>{a.title}</Text>
            </Pressable>
          ))}
          <Pressable onPress={onClose} style={[s.row, s.cancel]}><Text style={[s.t, { fontWeight: '700' }]}>Отмена</Text></Pressable>
        </View>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: 'rgba(13,17,23,.4)', justifyContent: 'flex-end', padding: 12 },
  sheet: { backgroundColor: C.card, borderRadius: 20, overflow: 'hidden' },
  row: { paddingVertical: 16, alignItems: 'center' },
  sep: { borderTopWidth: 1, borderTopColor: C.line },
  cancel: { borderTopWidth: 6, borderTopColor: C.bg },
  t: { fontSize: 17, color: C.ink },
});
