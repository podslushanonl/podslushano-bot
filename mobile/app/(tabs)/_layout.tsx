import { SymbolView } from 'expo-symbols';
import { Tabs } from 'expo-router';
import type { ColorValue } from 'react-native';
import { C } from '@/constants/theme';

type Icon = { ios: string; android: string; web: string };
function TabIcon({ name, color }: { name: Icon; color: ColorValue }) {
  return <SymbolView name={name as any} tintColor={color} size={26} />;
}
const icon = (name: Icon) => function Icon({ color }: { color: ColorValue }) { return <TabIcon name={name} color={color} />; };

export default function TabLayout() {
  return (
    <Tabs screenOptions={{
      tabBarActiveTintColor: C.accent, tabBarInactiveTintColor: C.muted,
      tabBarStyle: { backgroundColor: C.card, borderTopColor: C.line },
      headerStyle: { backgroundColor: C.bg }, headerShadowVisible: false,
      headerTitleStyle: { fontWeight: '800', fontSize: 20, color: C.ink },
    }}>
      <Tabs.Screen name="index" options={{ title: 'Лента', headerShown: false,
        tabBarIcon: icon({ ios: 'newspaper.fill', android: 'newspaper', web: 'newspaper' }) }} />
      <Tabs.Screen name="afisha" options={{ title: 'Афиша',
        tabBarIcon: icon({ ios: 'ticket.fill', android: 'confirmation_number', web: 'confirmation_number' }) }} />
      <Tabs.Screen name="trains" options={{ title: 'Поезда NS',
        tabBarIcon: icon({ ios: 'tram.fill', android: 'train', web: 'train' }) }} />
      <Tabs.Screen name="more" options={{ title: 'Ещё',
        tabBarIcon: icon({ ios: 'ellipsis.circle.fill', android: 'more_horiz', web: 'more_horiz' }) }} />
    </Tabs>
  );
}
