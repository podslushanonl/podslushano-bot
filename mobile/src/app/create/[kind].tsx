import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { CREATE, CreateKind } from '@/features/create/CreateSheet';
import { HAIRLINE, radius, space, useTheme } from '@/theme';
import { Button, Card, Icon, LargeTitle, PageScreen, Txt, useToast } from '@/ui';

// Шаги каждой формы. Сами формы, загрузка фото и оплата Mollie — этап 5.
const STEPS: Record<CreateKind, string[]> = {
  event: ['Название, дата и время', 'Город и площадка', 'Постер 16:9 и описание', 'Предпросмотр карточки', 'Оплата €9,99 через iDEAL'],
  card: ['Имя и профессия', 'Город или «Онлайн»', 'Описание услуг и фото', 'Telegram и WhatsApp для связи', 'Оплата €9,99 через iDEAL'],
  suggest: ['Что случилось или какой у вас вопрос', 'Город', 'Фото (по желанию)', 'Отправка в редакцию'],
};

/** Экран создания из кнопки «+»: событие, карточка специалиста или новость. Сейчас — каркас с шагами. */
export default function Create() {
  const { c } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const { kind } = useLocalSearchParams<{ kind: CreateKind }>();
  const o = CREATE.find((x) => x.kind === kind) || CREATE[0];
  const steps = STEPS[o.kind];
  // Гостевой режим: вход нужен только здесь, на целевом действии
  const start = () => (user ? toast('Форма появится на этапе 5. Каркас и навигация уже работают.', 'info') : router.push('/login'));
  return (
    <PageScreen title={o.title}
      footer={<Button kind="accent" icon={user ? o.icon : 'person'} title={user ? (o.price ? `Начать · ${o.price}` : 'Начать') : 'Войти, чтобы продолжить'} onPress={start} />}>
      <LargeTitle title={o.title} sub={o.sub} />
      <Card pad={16} style={{ gap: 0 }}>
        {steps.map((s, i) => (
          <View key={s} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12,
            borderTopWidth: i ? HAIRLINE : 0, borderTopColor: c.line }}>
            <View style={{ width: 28, height: 28, borderRadius: 14, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
              <Txt v="caption" tone="accent" style={{ fontWeight: '700' }}>{i + 1}</Txt>
            </View>
            <Txt v="callout" tone="ink" style={{ flex: 1 }}>{s}</Txt>
          </View>
        ))}
      </Card>
      <View style={{ flexDirection: 'row', gap: space.gap, padding: 14, borderRadius: radius.card, backgroundColor: c.secondarySoft }}>
        <Icon name="info" size={20} color={c.secondary} />
        <Txt v="footnote" color={c.secondary} style={{ flex: 1 }}>
          {o.price
            ? 'Оплата проходит на защищённой странице Mollie (iDEAL). После оплаты вы вернётесь в приложение, а размещение появится после проверки редакцией.'
            : 'Это бесплатно. Редакция прочитает сообщение и ответит, если понадобятся детали.'}
        </Txt>
      </View>
    </PageScreen>
  );
}
