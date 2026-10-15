import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { useColorScheme } from 'react-native';
import { useAuth } from '@/api/auth';
import { useConversations } from '@/api/dm';
import { palette } from '@/theme';


/** Системные вкладки на телефоне (iOS / Android) в цветах светлой или тёмной темы. */
export default function AppTabs() {
  const { user } = useAuth();
  const unread = useConversations(!!user).data?.unread || 0;
  const t = useColorScheme() === 'dark' ? palette.dark : palette.light;
  return (
    // Классическая панель в цветах темы: активная вкладка — фирменный оранжевый, остальные приглушены
    <NativeTabs tintColor={t.accent} iconColor={{ default: t.iconOff, selected: t.accent }}
      labelStyle={{ default: { color: t.iconOff }, selected: { color: t.accent } }}
      backgroundColor={t.bgElevated} badgeBackgroundColor={t.accent}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} md="home" />
        <NativeTabs.Trigger.Label>Главная</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="pulse">
        <NativeTabs.Trigger.Icon sf={{ default: 'play.rectangle.on.rectangle', selected: 'play.rectangle.on.rectangle.fill' }} md="smart_display" />
        <NativeTabs.Trigger.Label>Pulse</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="messages">
        <NativeTabs.Trigger.Icon sf={{ default: 'bubble.left.and.bubble.right', selected: 'bubble.left.and.bubble.right.fill' }} md="forum" />
        <NativeTabs.Trigger.Label>Сообщения</NativeTabs.Trigger.Label>
        {unread ? <NativeTabs.Trigger.Badge>{unread > 99 ? '99+' : String(unread)}</NativeTabs.Trigger.Badge> : null}
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="market">
        <NativeTabs.Trigger.Icon sf={{ default: 'bag', selected: 'bag.fill' }} md="shopping_bag" />
        <NativeTabs.Trigger.Label>Барахолка</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="profile">
        <NativeTabs.Trigger.Icon sf={{ default: 'person.crop.circle', selected: 'person.crop.circle.fill' }} md="account_circle" />
        <NativeTabs.Trigger.Label>Профиль</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
