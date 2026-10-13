import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { DynamicColorIOS, Platform } from 'react-native';
import { useAuth } from '@/api/auth';
import { useConversations } from '@/api/dm';
import { palette } from '@/theme';

const ink = Platform.OS === 'ios' ? DynamicColorIOS({ light: palette.light.ink, dark: palette.dark.ink }) : palette.light.ink;

/** Системные вкладки: на iOS 26+ — настоящее Liquid Glass, на Android — Material. */
export default function AppTabs() {
  const { user } = useAuth();
  const unread = useConversations(!!user).data?.unread || 0;
  return (
    <NativeTabs tintColor={ink} labelStyle={{ color: ink }} minimizeBehavior="onScrollDown" badgeBackgroundColor={palette.light.accent}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} md="home" />
        <NativeTabs.Trigger.Label>Главная</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="market">
        <NativeTabs.Trigger.Icon sf={{ default: 'bag', selected: 'bag.fill' }} md="shopping_bag" />
        <NativeTabs.Trigger.Label>Барахолка</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="messages">
        <NativeTabs.Trigger.Icon sf={{ default: 'bubble.left.and.bubble.right', selected: 'bubble.left.and.bubble.right.fill' }} md="forum" />
        <NativeTabs.Trigger.Label>Сообщения</NativeTabs.Trigger.Label>
        {unread ? <NativeTabs.Trigger.Badge>{unread > 99 ? '99+' : String(unread)}</NativeTabs.Trigger.Badge> : null}
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="profile">
        <NativeTabs.Trigger.Icon sf={{ default: 'person.crop.circle', selected: 'person.crop.circle.fill' }} md="account_circle" />
        <NativeTabs.Trigger.Label>Профиль</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
