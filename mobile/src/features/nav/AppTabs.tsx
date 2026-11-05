import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { useColorScheme } from 'react-native';
import { palette } from '@/theme';

/** Системные вкладки на телефоне (iOS / Android): пять разделов, активный — фирменный оранжевый. */
export default function AppTabs() {
  const t = useColorScheme() === 'dark' ? palette.dark : palette.light;
  return (
    <NativeTabs tintColor={t.accent} iconColor={{ default: t.iconOff, selected: t.accent }}
      labelStyle={{ default: { color: t.iconOff }, selected: { color: t.accent } }}
      backgroundColor={t.bgElevated}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Icon sf={{ default: 'sun.max', selected: 'sun.max.fill' }} md="light_mode" />
        <NativeTabs.Trigger.Label>Сегодня</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="afisha">
        <NativeTabs.Trigger.Icon sf={{ default: 'ticket', selected: 'ticket.fill' }} md="confirmation_number" />
        <NativeTabs.Trigger.Label>Афиша</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="places">
        <NativeTabs.Trigger.Icon sf={{ default: 'mappin.and.ellipse', selected: 'mappin.circle.fill' }} md="location_on" />
        <NativeTabs.Trigger.Label>Места</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="guide">
        <NativeTabs.Trigger.Icon sf={{ default: 'book', selected: 'book.fill' }} md="menu_book" />
        <NativeTabs.Trigger.Label>Гид</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="shop">
        <NativeTabs.Trigger.Icon sf={{ default: 'bag', selected: 'bag.fill' }} md="shopping_bag" />
        <NativeTabs.Trigger.Label>Магазин</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
