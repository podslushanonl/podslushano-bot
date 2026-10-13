import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Modal, Platform, Pressable, View } from 'react-native';
import Animated, { FadeIn, FadeInDown, FadeOut, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { radius, useTheme } from '@/theme';
import { Glass } from './Glass';
import { Icon, IconName } from './Icon';
import { Tap } from './Tap';
import { Txt } from './Text';

export type SheetAction = { title: string; icon?: IconName; danger?: boolean; onPress: () => void };

/** Меню действий снизу на стекле — одинаково на iOS, Android и в браузере. */
export function ActionSheet({ visible, title, actions, onClose }: { visible: boolean; title?: string; actions: SheetAction[]; onClose: () => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end', padding: 10, paddingBottom: insets.bottom + 10 }} onPress={onClose}
        accessibilityLabel="Закрыть">
        <Pressable onPress={() => {}} style={{ gap: 8 }}>
          <Glass radius={radius.xl} strong>
            {title ? <Txt v="footnote" center style={{ paddingTop: 14, paddingBottom: 6, paddingHorizontal: 20 }}>{title}</Txt> : null}
            {actions.map((a, i) => (
              <Tap key={a.title} scaleTo={0.98} onPress={() => { onClose(); setTimeout(a.onPress, Platform.OS === 'ios' ? 250 : 0); }}
                style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 17,
                  borderTopWidth: i || title ? 1 : 0, borderTopColor: c.line }}>
                {a.icon ? <Icon name={a.icon} size={18} color={a.danger ? c.danger : c.ink} /> : null}
                <Txt v="bodyStrong" color={a.danger ? c.danger : c.ink}>{a.title}</Txt>
              </Tap>
            ))}
          </Glass>
          <Glass radius={radius.xl} strong>
            <Tap scaleTo={0.98} onPress={onClose} style={{ paddingVertical: 17, alignItems: 'center' }}>
              <Txt v="bodyStrong" style={{ fontFamily: 'Onest_700Bold' }}>Отмена</Txt>
            </Tap>
          </Glass>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// ---- Всплывающие уведомления (тосты) сверху экрана, на стекле

type ToastMsg = { id: number; text: string; tone: 'ok' | 'error' | 'info' };
const ToastCtx = createContext<(text: string, tone?: ToastMsg['tone']) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastHost({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<ToastMsg | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();
  const { c } = useTheme();
  const show = useCallback((text: string, tone: ToastMsg['tone'] = 'ok') => {
    if (timer.current) clearTimeout(timer.current);
    setMsg({ id: Date.now(), text, tone });
    timer.current = setTimeout(() => setMsg(null), 2600);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg ? (
        <Animated.View key={msg.id} entering={FadeInDown.springify().damping(16)} exiting={FadeOutUp} pointerEvents="none"
          style={{ position: 'absolute', top: insets.top + 8, left: 16, right: 16, zIndex: 100, alignItems: 'center' }}>
          <Glass radius={radius.pill} strong style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 18, paddingVertical: 12, maxWidth: 520 }}>
            <Icon name={msg.tone === 'error' ? 'warning' : msg.tone === 'info' ? 'info' : 'check'} size={18}
              color={msg.tone === 'error' ? c.danger : msg.tone === 'info' ? c.info : c.success} />
            <Txt v="callout" tone="ink" style={{ flexShrink: 1 }}>{msg.text}</Txt>
          </Glass>
        </Animated.View>
      ) : null}
    </ToastCtx.Provider>
  );
}

/** Мягкое появление блока при первом показе. */
export function Appear({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  return <Animated.View entering={FadeIn.duration(260).delay(delay)} exiting={FadeOut.duration(120)}>{children}</Animated.View>;
}

export function Spacer({ h = 8 }: { h?: number }) {
  return <View style={{ height: h }} />;
}
