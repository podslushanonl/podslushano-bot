import * as Location from 'expo-location';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { setProvince, useProvince } from '@/lib/province';
import { nearestProvince, PROVINCES, ProvinceId } from '@/lib/provinces';
import { useTheme } from '@/theme';
import { Button, Group, Icon, PageScreen, Row, Txt, useToast } from '@/ui';

/** Выбор провинции. first=1 — первый запуск: после выбора открываются разделы, кнопки «назад» нет. */
export default function ProvincePicker() {
  const { c } = useTheme();
  const { first } = useLocalSearchParams<{ first?: string }>();
  const { province } = useProvince();
  const toast = useToast();
  const [locating, setLocating] = useState(false);
  const [suggested, setSuggested] = useState<ProvinceId | null>(null);

  const choose = (id: ProvinceId) => {
    setProvince(id);
    if (first) router.replace('/');
    else router.back();
  };

  const locate = async () => {
    setLocating(true);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) { toast('Доступ к геолокации не дан. Выберите провинцию из списка.'); return; }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
      setSuggested(nearestProvince(pos.coords.latitude, pos.coords.longitude).id);
    } catch {
      toast('Не получилось определить место. Выберите провинцию из списка.');
    } finally {
      setLocating(false);
    }
  };

  const sug = PROVINCES.find((p) => p.id === suggested);

  return (
    <PageScreen title="Провинция" topInset>
      <View style={{ gap: 8 }}>
        <Txt v="title1" accessibilityRole="header">{first ? 'Где вы живёте?' : 'Ваша провинция'}</Txt>
        <Txt v="callout" tone="muted">
          Афиша, места и контакт-гайд будут из этой провинции. Сменить её можно в любой момент в шапке раздела.
        </Txt>
      </View>

      {sug ? (
        <Group title="По геолокации">
          <Row first title={sug.name} sub={`Столица: ${sug.capital}`} icon="location" iconBg={c.accent} onPress={() => choose(sug.id)} />
        </Group>
      ) : (
        <Button kind="secondary" icon="location" title="Определить по геолокации" loading={locating} onPress={locate} />
      )}

      <Group title="Все провинции">
        {PROVINCES.map((p, i) => (
          <Row key={p.id} first={i === 0} title={p.name} sub={p.short} onPress={() => choose(p.id)} chevron={false}
            right={province?.id === p.id ? <Icon name="check" size={18} color={c.accentText} /> : null} />
        ))}
      </Group>
    </PageScreen>
  );
}
