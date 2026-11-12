import { BlurView } from 'expo-blur';
import * as Haptics from 'expo-haptics';
import { TabList, TabSlot, TabTrigger, Tabs, TabTriggerSlotProps } from 'expo-router/ui';
import { forwardRef, useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { CreateSheet } from '@/features/create/CreateSheet';
import { HAIRLINE, useTheme } from '@/theme';
import { emitTabReselect, Icon, IconName, Txt } from '@/ui';

// Четыре раздела и центральная кнопка «+»: Лента — События — [+] — Гид — Профиль.
type Href = '/' | '/events' | '/guide' | '/profile';
const TABS: { name: string; href: Href; title: string; icon: IconName; iconOn: IconName }[] = [
  { name: 'index', href: '/', title: 'Лента', icon: 'newspaper', iconOn: 'newspaper' },
  { name: 'events', href: '/events', title: 'События', icon: 'ticket', iconOn: 'ticketFill' },
  { name: 'guide', href: '/guide', title: 'Гид', icon: 'guide', iconOn: 'guideFill' },
  { name: 'profile', href: '/profile', title: 'Профиль', icon: 'person', iconOn: 'personFill' },
];
export const BAR_HEIGHT = 52;   // вместе с SafeArea на iPhone выходит около 86pt
const light = () => { if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {}); };

type BtnProps = TabTriggerSlotProps & { title: string; icon: IconName; iconOn: IconName };

const TabButton = forwardRef<View, BtnProps>(function TabButton({ isFocused, title, icon, iconOn, style, ...props }, ref) {
  const { c } = useTheme();
  const tint = isFocused ? c.accent : c.iconOff;
  return (
    <Pressable ref={ref} {...props} onPress={(e) => { light(); if (isFocused) emitTabReselect(); props.onPress?.(e); }}
      accessibilityRole="tab" accessibilityState={{ selected: !!isFocused }} accessibilityLabel={title}
      style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 2, height: BAR_HEIGHT }}>
      <Icon name={isFocused ? iconOn : icon} size={24} color={tint} />
      <Txt v="caption" color={tint} style={{ fontSize: 10.5, fontWeight: isFocused ? '700' : '500' }}>{title}</Txt>
    </Pressable>
  );
});

/** Нижнее меню: полупрозрачный блюр на iOS, плотный фон на Android, в центре — кнопка создания. */
export default function AppTabs() {
  const insets = useSafeAreaInsets();
  const { c, dark } = useTheme();
  const [create, setCreate] = useState(false);
  const tab = (i: number) => (
    <TabTrigger key={TABS[i].name} name={TABS[i].name} asChild>
      <TabButton title={TABS[i].title} icon={TABS[i].icon} iconOn={TABS[i].iconOn} />
    </TabTrigger>
  );
  return (
    <Tabs style={{ flex: 1 }}>
      <TabSlot style={{ flex: 1 }} />
      <TabList style={{ display: 'none' }}>
        {TABS.map((t) => <TabTrigger key={t.name} name={t.name} href={t.href} />)}
      </TabList>
      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, borderTopWidth: HAIRLINE, borderTopColor: c.line,
        backgroundColor: Platform.OS === 'ios' ? 'transparent' : c.bgElevated }}>
        {Platform.OS === 'ios' ? <BlurView intensity={80} tint={dark ? 'systemChromeMaterialDark' : 'systemChromeMaterialLight'} style={StyleSheet.absoluteFill} /> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', paddingBottom: Math.max(insets.bottom, 8), paddingHorizontal: 4 }}>
          {tab(0)}
          {tab(1)}
          <View style={{ width: 72, alignItems: 'center' }}>
            <Pressable onPress={() => { light(); setCreate(true); }} accessibilityRole="button" accessibilityLabel="Добавить: событие, карточку или новость"
              hitSlop={6} style={({ pressed }) => ({ width: 56, height: 56, borderRadius: 28, marginTop: -18, backgroundColor: c.accent,
                alignItems: 'center', justifyContent: 'center', borderWidth: 4, borderColor: c.bgElevated,
                transform: [{ scale: pressed ? 0.94 : 1 }], boxShadow: '0 4px 12px rgba(255,90,31,0.35)' })}>
              <Icon name="plus" size={26} color={c.onAccent} />
            </Pressable>
          </View>
          {tab(2)}
          {tab(3)}
        </View>
      </View>
      <CreateSheet visible={create} onClose={() => setCreate(false)} />
    </Tabs>
  );
}
