import { TabList, TabSlot, TabTrigger, Tabs, TabTriggerSlotProps } from 'expo-router/ui';
import { forwardRef } from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HAIRLINE, useTheme } from '@/theme';
import { Badge, emitTabReselect, Icon, IconName, Txt } from '@/ui';

// Пять разделов: Сегодня — Афиша — Места — Гид — Магазин. Профиль открывается из шапки.
const TABS: { name: string; href: '/' | '/afisha' | '/places' | '/guide' | '/shop'; title: string; icon: IconName; iconOn: IconName }[] = [
  { name: 'index', href: '/', title: 'Сегодня', icon: 'sun', iconOn: 'sunFill' },
  { name: 'afisha', href: '/afisha', title: 'Афиша', icon: 'ticket', iconOn: 'ticketFill' },
  { name: 'places', href: '/places', title: 'Места', icon: 'pin', iconOn: 'pinFill' },
  { name: 'guide', href: '/guide', title: 'Гид', icon: 'guide', iconOn: 'guideFill' },
  { name: 'shop', href: '/shop', title: 'Магазин', icon: 'market', iconOn: 'marketFill' },
];

type BtnProps = TabTriggerSlotProps & { title: string; icon: IconName; iconOn: IconName; badge?: number };

const TabButton = forwardRef<View, BtnProps>(function TabButton({ isFocused, title, icon, iconOn, badge, style, ...props }, ref) {
  const { c } = useTheme();
  // Активная вкладка выделяется только цветом: фирменный оранжевый; остальные — приглушённые
  const tint = isFocused ? c.accent : c.iconOff;
  return (
    <Pressable ref={ref} {...props} onPress={(e) => { if (isFocused) emitTabReselect(); props.onPress?.(e); }}
      accessibilityRole="tab" accessibilityState={{ selected: !!isFocused }} accessibilityLabel={title}
      style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3, height: 54 }}>
      <Icon name={isFocused ? iconOn : icon} size={24} color={tint} />
      {badge ? <View style={{ position: 'absolute', top: 3, left: '54%' }}><Badge n={badge} /></View> : null}
      <Txt v="caption" color={tint} style={{ fontSize: 10.5, fontFamily: isFocused ? 'Onest_700Bold' : 'Onest_600SemiBold' }}>{title}</Txt>
    </Pressable>
  );
});

/** В браузере системных вкладок нет: классическая панель на всю ширину, как в Threads и системных приложениях iOS. */
export default function AppTabs() {
  const insets = useSafeAreaInsets();
  const { c } = useTheme();
  return (
    <Tabs style={{ flex: 1 }}>
      <TabSlot style={{ flex: 1 }} />
      <TabList style={{ display: 'none' }}>
        {TABS.map((t) => <TabTrigger key={t.name} name={t.name} href={t.href} />)}
      </TabList>
      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, flexDirection: 'row', backgroundColor: c.bgElevated,
        borderTopWidth: HAIRLINE, borderTopColor: c.line, paddingBottom: Math.max(insets.bottom, 6), paddingHorizontal: 6 }}>
        {TABS.map((t) => (
          <TabTrigger key={t.name} name={t.name} asChild>
            <TabButton title={t.title} icon={t.icon} iconOn={t.iconOn} />
          </TabTrigger>
        ))}
      </View>
    </Tabs>
  );
}
