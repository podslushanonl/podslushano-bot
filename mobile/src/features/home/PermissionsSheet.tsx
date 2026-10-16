import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { askCameraAndMic, locateMe } from '@/lib/location';
import { radius, useTheme } from '@/theme';
import { Button, Icon, IconName, Txt, useToast } from '@/ui';

const KEY = 'pn_perm_asked_v1';

function Item({ icon, bg, title, text }: { icon: IconName; bg: string; title: string; text: string }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
      <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: bg, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} size={21} color="#FFFFFF" />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="bodyStrong">{title}</Txt>
        <Txt v="footnote" tone="muted">{text}</Txt>
      </View>
    </View>
  );
}

/** Один раз после входа: объясняем, зачем геолокация, камера и микрофон, — и только потом системные запросы. */
export function PermissionsSheet() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const needed = !!user && !user.located;
  useEffect(() => {
    if (!needed) return;
    AsyncStorage.getItem(KEY).then((v) => { if (!v) setOpen(true); }).catch(() => {});
  }, [needed]);
  const close = () => { setOpen(false); AsyncStorage.setItem(KEY, '1').catch(() => {}); };
  const allow = async () => {
    setBusy(true);
    try {
      const p = await locateMe().catch((e) => { toast(e?.message || 'Место не определилось', 'error'); return null; });
      await askCameraAndMic();
      if (p) toast(`Ваше место: ${p.name}`);
    } finally { setBusy(false); close(); }
  };
  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={close} statusBarTranslucent>
      <Pressable onPress={close} accessibilityLabel="Закрыть" style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end' }}>
        <Pressable onPress={() => {}} style={{ backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
          padding: 22, paddingBottom: insets.bottom + 18, gap: 18 }}>
          <View style={{ alignSelf: 'center', width: 38, height: 5, borderRadius: 3, backgroundColor: c.line, marginTop: -8 }} />
          <View style={{ gap: 6 }}>
            <Txt v="title2">Сделаем podslushano своим</Txt>
            <Txt v="callout" tone="muted">Телефон спросит разрешения — вот зачем они нужны.</Txt>
          </View>
          <Item icon="location" bg="#007AFF" title="Геолокация" text="Ваш город или деревня и посты соседей в радиусе 50 км в ленте «Рядом»" />
          <Item icon="camera2" bg="#FF6A1A" title="Камера" text="Фото и видео для постов, историй и Pulse" />
          <Item icon="mic" bg="#34C759" title="Микрофон" text="Звук в ваших видео" />
          <View style={{ gap: 8 }}>
            <Button title="Разрешить" kind="accent" loading={busy} onPress={allow} />
            <Button title="Не сейчас" kind="plain" disabled={busy} onPress={close} />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
