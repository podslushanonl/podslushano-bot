import { Image } from 'expo-image';
import { useState } from 'react';
import { Modal, StatusBar, useWindowDimensions, View } from 'react-native';
import { Gesture, GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button, Txt } from '@/ui';

/** Рамка в долях картинки — так её и понимает сервер (POST /api/app/me/avatar {crop}). */
export type Crop = { x: number; y: number; w: number; h: number };

const MAX_ZOOM = 5;

/** Кадрирование аватара: фото двигается пальцем и масштабируется щипком внутри круга. */
export function AvatarCropper({ uri, onDone, onCancel }: { uri: string | null; onDone: (crop: Crop) => void; onCancel: () => void }) {
  return (
    <Modal visible={!!uri} animationType="slide" onRequestClose={onCancel} statusBarTranslucent>
      {uri ? <Cropper key={uri} uri={uri} onDone={onDone} onCancel={onCancel} /> : null}
    </Modal>
  );
}

function Cropper({ uri, onDone, onCancel }: { uri: string; onDone: (crop: Crop) => void; onCancel: () => void }) {
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const S = Math.min(width - 40, height - insets.top - insets.bottom - 220, 420);   // сторона рамки
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const zoom = useSharedValue(1);
  const savedZoom = useSharedValue(1);
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const sx = useSharedValue(0);
  const sy = useSharedValue(0);

  // Картинка вписана «с заполнением»: короткая сторона = рамке
  const base = size ? S / Math.min(size.w, size.h) : 1;
  const dw = size ? size.w * base : S;
  const dh = size ? size.h * base : S;

  const limit = (v: number, z: number, side: number) => {
    'worklet';
    const max = Math.max(0, (side * z - S) / 2);
    return Math.min(max, Math.max(-max, v));
  };

  const pinch = Gesture.Pinch()
    .onUpdate((e) => {
      const z = Math.min(MAX_ZOOM, Math.max(1, savedZoom.get() * e.scale));
      zoom.set(z);
      tx.set(limit(tx.get(), z, dw)); ty.set(limit(ty.get(), z, dh));
    })
    .onEnd(() => { savedZoom.set(zoom.get()); sx.set(tx.get()); sy.set(ty.get()); });
  const pan = Gesture.Pan()
    .averageTouches(true)
    .onUpdate((e) => { tx.set(limit(sx.get() + e.translationX, zoom.get(), dw)); ty.set(limit(sy.get() + e.translationY, zoom.get(), dh)); })
    .onEnd(() => { sx.set(tx.get()); sy.set(ty.get()); });
  const doubleTap = Gesture.Tap().numberOfTaps(2).onEnd(() => {
    const z = savedZoom.get() > 1.01 ? 1 : 2;
    savedZoom.set(z); zoom.set(withTiming(z));
    const nx = limit(tx.get(), z, dw);
    const ny = limit(ty.get(), z, dh);
    sx.set(nx); sy.set(ny); tx.set(withTiming(nx)); ty.set(withTiming(ny));
  });

  const imgStyle = useAnimatedStyle(() => ({ transform: [{ translateX: tx.get() }, { translateY: ty.get() }, { scale: zoom.get() }] }));

  const done = () => {
    if (!size) return;
    const k = base * zoom.get();                   // экранных точек на пиксель картинки
    const side = S / k;                            // сторона рамки в пикселях картинки
    const cx = size.w / 2 - tx.get() / k;
    const cy = size.h / 2 - ty.get() / k;
    onDone({ x: (cx - side / 2) / size.w, y: (cy - side / 2) / size.h, w: side / size.w, h: side / size.h });
  };

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: '#000' }}>
      <StatusBar barStyle="light-content" />
      <View style={{ paddingTop: insets.top + 18, paddingHorizontal: 20, gap: 6 }}>
        <Txt v="title2" color="#fff" center>Фото профиля</Txt>
        <Txt v="subhead" color="rgba(255,255,255,0.65)" center>Передвиньте и масштабируйте фото</Txt>
      </View>
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        <GestureDetector gesture={Gesture.Simultaneous(pinch, pan, doubleTap)}>
          <View style={{ width: S, height: S, alignItems: 'center', justifyContent: 'center' }}>
            {/* Фото может выходить за рамку: видно, что останется за кадром */}
            <Animated.View style={[{ width: dw, height: dh }, imgStyle]}>
              <Image source={uri} contentFit="cover" style={{ width: dw, height: dh }}
                onLoad={(e) => setSize({ w: e.source.width, h: e.source.height })} accessibilityLabel="Фото для аватара" />
            </Animated.View>
            {/* Затемнение вокруг круга */}
            <View pointerEvents="none" style={{ position: 'absolute', width: S + 2000, height: S + 2000, borderRadius: (S + 2000) / 2,
              borderWidth: 1000, borderColor: 'rgba(0,0,0,0.62)' }} />
            <View pointerEvents="none" style={{ position: 'absolute', width: S, height: S, borderRadius: S / 2, borderWidth: 1.5,
              borderColor: 'rgba(255,255,255,0.85)' }} />
          </View>
        </GestureDetector>
      </View>
      <View style={{ flexDirection: 'row', gap: 12, paddingHorizontal: 20, paddingBottom: insets.bottom + 16 }}>
        <Button title="Отмена" kind="secondary" onPress={onCancel} style={{ flex: 1 }} />
        <Button title="Готово" kind="accent" disabled={!size} onPress={done} style={{ flex: 1 }} />
      </View>
    </GestureHandlerRootView>
  );
}
