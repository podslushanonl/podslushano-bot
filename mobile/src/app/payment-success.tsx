import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { space, useTheme } from '@/theme';
import { Button, EmptyState } from '@/ui';

/**
 * Возврат из оплаты Mollie по ссылке podslushano://payment-success?id=…
 * На этапе 5 экран спросит у сервера статус платежа; сейчас показывает итог и ведёт в кабинет.
 */
export default function PaymentSuccess() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id?: string }>();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: 'center', paddingHorizontal: space.screen, paddingBottom: insets.bottom }}>
      <EmptyState icon="check" title="Оплата получена"
        text={`Спасибо! Размещение появится после проверки редакцией.${id ? ` Номер платежа: ${id}.` : ''}`}
        action={(
          <View style={{ gap: space.gap }}>
            <Button kind="accent" title="Открыть кабинет бизнеса" onPress={() => router.replace('/business')} />
            <Button kind="secondary" title="На главную" onPress={() => router.replace('/')} />
          </View>
        )} />
    </View>
  );
}
