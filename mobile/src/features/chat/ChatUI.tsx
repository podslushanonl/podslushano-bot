import { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, TextInput, View } from 'react-native';
import Animated, { FadeInUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { timeLabel } from '@/features/feed/cards';
import { radius, type as T, useTheme } from '@/theme';
import { Glass, Icon, IconButton, Tap, Txt } from '@/ui';

/** Пузырь сообщения: свои — тёмные справа, чужие — светлые слева. */
export function Bubble({ text, at, mine, name, read, onLongPress, fresh }: {
  text: string; at: string; mine: boolean; name?: string; read?: boolean; onLongPress?: () => void; fresh?: boolean;
}) {
  const { c } = useTheme();
  const body = (
    <Pressable onLongPress={onLongPress} delayLongPress={280} accessibilityHint={onLongPress ? 'Удерживайте для действий' : undefined}
      style={{ alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '82%', paddingHorizontal: 14, paddingVertical: 9, gap: 2,
        backgroundColor: mine ? c.inverse : c.bgElevated, borderWidth: mine ? 0 : 1, borderColor: c.line,
        borderRadius: 22, borderBottomRightRadius: mine ? 7 : 22, borderBottomLeftRadius: mine ? 22 : 7 }}>
      {name ? <Txt v="caption" tone="accent" style={{ fontFamily: 'Onest_700Bold' }}>{name}</Txt> : null}
      <Txt v="body" color={mine ? c.onInverse : c.ink} selectable>{text}</Txt>
      <View style={{ flexDirection: 'row', alignSelf: 'flex-end', alignItems: 'center', gap: 4 }}>
        <Txt v="caption" color={mine ? c.onInverseMuted : c.faint} style={{ fontSize: 11 }}>{timeLabel(at)}</Txt>
        {mine && read !== undefined ? <Icon name="check" size={11} color={read ? c.accent : c.onInverseMuted} /> : null}
      </View>
    </Pressable>
  );
  return fresh ? <Animated.View entering={FadeInUp.springify().damping(18)}>{body}</Animated.View> : body;
}

/** Поле ввода сообщения на стекле, кнопка отправки — фирменная оранжевая. */
export function Composer({ value, onChange, onSend, busy, placeholder = 'Сообщение', onFocus, disabled }: {
  value: string; onChange: (v: string) => void; onSend: () => void; busy?: boolean; placeholder?: string; onFocus?: () => void; disabled?: boolean;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const can = !!value.trim() && !busy && !disabled;
  return (
    <View style={{ paddingHorizontal: 10, paddingTop: 8, paddingBottom: Math.max(insets.bottom, 10) }}>
      <Glass radius={28} strong style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 6, padding: 5, paddingLeft: 16 }}>
        <TextInput value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={c.faint} multiline maxLength={1000}
          onFocus={onFocus} editable={!disabled} accessibilityLabel="Сообщение"
          style={[T.body, { flex: 1, color: c.ink, maxHeight: 130, minHeight: 44, paddingTop: 11, paddingBottom: 11, outlineStyle: 'none' } as any]} />
        <Tap onPress={onSend} disabled={!can} haptic="light" scaleTo={0.88} accessibilityLabel="Отправить"
          style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: can ? c.accent : c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="send" size={20} color={can ? c.onAccent : c.faint} />
        </Tap>
      </Glass>
    </View>
  );
}

/** Каркас экрана переписки: шапка на стекле сверху, лента, поле ввода снизу; клавиатура не перекрывает поле. */
export function ChatShell({ header, children, composer }: { header: ReactNode; children: ReactNode; composer: ReactNode }) {
  const { c } = useTheme();
  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={{ flex: 1 }}>{children}</View>
      {composer}
      {header}
    </KeyboardAvoidingView>
  );
}

/** Шапка переписки: «назад», аватар/название, действия. */
export function ChatHeader({ title, sub, left, right, below, onBack }: { title: string; sub?: string; left?: ReactNode; right?: ReactNode; below?: ReactNode; onBack: () => void }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ position: 'absolute', top: 0, left: 0, right: 0 }}>
      <Glass radius={0} strong style={{ paddingTop: insets.top + 4, paddingBottom: 10, paddingHorizontal: 10, gap: 10, borderWidth: 0, borderBottomWidth: 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <IconButton icon="back" label="Назад" kind="plain" onPress={onBack} />
          {left}
          <View style={{ flex: 1 }}>
            <Txt v="headline" numberOfLines={1}>{title}</Txt>
            {sub ? <Txt v="caption" numberOfLines={1}>{sub}</Txt> : null}
          </View>
          {right}
        </View>
        {below}
      </Glass>
    </View>
  );
}

export const CHAT_HEADER_SPACE = (top: number, extra = 0) => top + 64 + extra;
export const bubbleRadius = radius.l;
