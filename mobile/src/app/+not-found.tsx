import { router } from 'expo-router';
import { View } from 'react-native';
import { useTheme } from '@/theme';
import { Button, Empty } from '@/ui';

export default function NotFound() {
  const { c } = useTheme();
  return (
    <View style={{ flex: 1, justifyContent: 'center', backgroundColor: c.bg, padding: 20 }}>
      <Empty icon="info" title="Такой страницы нет" text="Возможно, ссылка устарела."
        action={<Button title="На главную" kind="primary" onPress={() => router.replace('/')} />} />
    </View>
  );
}
