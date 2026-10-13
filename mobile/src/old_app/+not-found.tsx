import { Link, Stack } from 'expo-router';
import { View } from 'react-native';
import { H, P } from '@/components/ui';

export default function NotFound() {
  return (
    <View style={{ flex: 1, padding: 24, gap: 12, justifyContent: 'center' }}>
      <Stack.Screen options={{ title: 'Не найдено' }} />
      <H size={22}>Такой страницы нет</H>
      <Link href="/"><P>На главную</P></Link>
    </View>
  );
}
