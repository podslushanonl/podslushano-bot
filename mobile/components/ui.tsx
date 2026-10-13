import { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';
import { C, R } from '@/constants/theme';

export function Card({ children, style, onPress }: { children: ReactNode; style?: ViewStyle; onPress?: () => void }) {
  if (!onPress) return <View style={[s.card, style]}>{children}</View>;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.card, style, pressed && { transform: [{ scale: 0.985 }], opacity: 0.95 }]}>
      {children}
    </Pressable>
  );
}

export function Eyebrow({ children, color = C.accent }: { children: ReactNode; color?: string }) {
  return <Text style={[s.eyebrow, { color }]}>{children}</Text>;
}

export function H({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return <Text style={[s.h, { fontSize: size, lineHeight: size * 1.22 }]}>{children}</Text>;
}

export function P({ children, muted, lines }: { children: ReactNode; muted?: boolean; lines?: number }) {
  return <Text numberOfLines={lines} style={[s.p, muted && { color: C.muted }]}>{children}</Text>;
}

export function Button({ title, onPress, soft, disabled }: { title: string; onPress: () => void; soft?: boolean; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityState={{ disabled: !!disabled }}
      style={({ pressed }) => [s.btn, soft ? s.btnSoft : s.btnAcc, pressed && { opacity: 0.85 }, disabled && { opacity: 0.55 }]}>
      <Text style={[s.btnT, soft && { color: C.ink }]}>{title}</Text>
    </Pressable>
  );
}

export function Loading() {
  return <View style={s.center}><ActivityIndicator color={C.accent} /></View>;
}

export function ErrorBox({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={s.center}>
      <P muted>Не получилось загрузить. Проверьте интернет.</P>
      <View style={{ height: 12 }} />
      <Button title="Повторить" onPress={onRetry} soft />
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: R.l, padding: 16, gap: 8, borderWidth: 1, borderColor: C.line,
    shadowColor: '#1E2846', shadowOpacity: 0.08, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 2 },
  eyebrow: { fontSize: 11.5, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
  h: { color: C.ink, fontWeight: '800', letterSpacing: -0.3 },
  p: { color: C.text, fontSize: 15, lineHeight: 21 },
  btn: { borderRadius: 999, paddingVertical: 13, paddingHorizontal: 20, alignItems: 'center' },
  btnAcc: { backgroundColor: C.accent },
  btnSoft: { backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  btnT: { color: '#fff', fontWeight: '700', fontSize: 15 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
});
