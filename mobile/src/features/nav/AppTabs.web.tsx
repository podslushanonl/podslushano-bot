import { TabList, TabSlot, TabTrigger, Tabs, TabTriggerSlotProps } from 'expo-router/ui';
import { forwardRef } from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { useConversations } from '@/api/dm';
import { useTheme } from '@/theme';
import { Badge, Glass, Icon, IconName, Txt } from '@/ui';

const TABS: { name: string; href: '/' | '/market' | '/messages' | '/profile'; title: string; icon: IconName; iconOn: IconName }[] = [
  { name: 'index', href: '/', title: 'Главная', icon: 'home', iconOn: 'homeFill' },
  { name: 'market', href: '/market', title: 'Барахолка', icon: 'market', iconOn: 'marketFill' },
  { name: 'messages', href: '/messages', title: 'Сообщения', icon: 'chat', iconOn: 'chatFill' },
  { name: 'profile', href: '/profile', title: 'Профиль', icon: 'person', iconOn: 'personFill' },
];

type BtnProps = TabTriggerSlotProps & { title: string; icon: IconName; iconOn: IconName; badge?: number };

const TabButton = forwardRef<View, BtnProps>(function TabButton({ isFocused, title, icon, iconOn, badge, style, ...props }, ref) {
  const { c } = useTheme();
  return (
    <Pressable ref={ref} {...props} accessibilityRole="tab" accessibilityState={{ selected: !!isFocused }} accessibilityLabel={title}
      style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 2, height: 56, borderRadius: 28,
        backgroundColor: isFocused ? c.glassFillStrong : 'transparent', ...(isFocused ? { boxShadow: '0 2px 10px rgba(11,13,18,0.08)' } as any : null) }}>
      <Icon name={isFocused ? iconOn : icon} size={23} color={isFocused ? c.ink : c.muted} />
      {badge ? <View style={{ position: 'absolute', top: 4, left: '54%' }}><Badge n={badge} /></View> : null}
      <Txt v="caption" color={isFocused ? c.ink : c.muted} style={{ fontSize: 11, fontFamily: isFocused ? 'Onest_700Bold' : 'Onest_600SemiBold' }}>{title}</Txt>
    </Pressable>
  );
});

/** В браузере системных вкладок нет: рисуем плавающую стеклянную панель как на iOS 26. */
export default function AppTabs() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const unread = useConversations(!!user).data?.unread || 0;
  return (
    <Tabs style={{ flex: 1 }}>
      <TabSlot style={{ flex: 1 }} />
      <TabList style={{ display: 'none' }}>
        {TABS.map((t) => <TabTrigger key={t.name} name={t.name} href={t.href} />)}
      </TabList>
      <View pointerEvents="box-none" style={{ position: 'absolute', left: 0, right: 0, bottom: Math.max(insets.bottom, 12) + 4, alignItems: 'center' }}>
        <Glass radius={34} style={{ flexDirection: 'row', padding: 5, width: '92%', maxWidth: 440 }}>
          {TABS.map((t) => (
            <TabTrigger key={t.name} name={t.name} asChild>
              <TabButton title={t.title} icon={t.icon} iconOn={t.iconOn} badge={t.name === 'messages' ? unread : 0} />
            </TabTrigger>
          ))}
        </Glass>
      </View>
    </Tabs>
  );
}
