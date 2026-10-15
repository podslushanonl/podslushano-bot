import { Image } from 'expo-image';
import { useEffect, useRef, useState } from 'react';
import { Modal, ScrollView, StatusBar, useWindowDimensions, View } from 'react-native';
import { Gesture, GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, { interpolate, SharedValue, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { scheduleOnRN } from 'react-native-worklets';
import { IconButton } from './Button';
import { Txt } from './Text';

const MAX = 4;
const DOUBLE = 2.5;

/** Фото на весь экран: листание, щипок и двойной тап для зума, смахивание вниз — закрыть. */
export function PhotoViewer({ urls, index, onClose }: { urls: string[]; index: number | null; onClose: () => void }) {
  return (
    <Modal visible={index !== null} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      {index !== null ? <Viewer key={index} urls={urls} start={index} onClose={onClose} /> : null}
    </Modal>
  );
}

function Viewer({ urls, start, onClose }: { urls: string[]; start: number; onClose: () => void }) {
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [page, setPage] = useState(start);
  const [zoomed, setZoomed] = useState(false);
  const dragY = useSharedValue(0);
  const list = useRef<ScrollView>(null);

  const backdrop = useAnimatedStyle(() => ({ opacity: interpolate(Math.abs(dragY.get()), [0, 300], [1, 0.25], 'clamp') }));
  const chrome = useAnimatedStyle(() => ({ opacity: interpolate(Math.abs(dragY.get()), [0, 80], [1, 0], 'clamp') }));

  return (
    <>
      <StatusBar barStyle="light-content" />
      <GestureHandlerRootView style={{ flex: 1 }}>
        <Animated.View style={[{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#000' }, backdrop]} />
        <ScrollView ref={list} horizontal onLayout={() => { if (start) list.current?.scrollTo({ x: start * width, animated: false }); }} pagingEnabled scrollEnabled={!zoomed && urls.length > 1} showsHorizontalScrollIndicator={false}
          onMomentumScrollEnd={(e) => setPage(Math.round(e.nativeEvent.contentOffset.x / width))}
          onScroll={(e) => setPage(Math.round(e.nativeEvent.contentOffset.x / width))} scrollEventThrottle={64}>
          {urls.map((u, i) => (
            <ZoomImage key={u} uri={u} w={width} h={height} active={i === page} dragY={dragY} onZoom={setZoomed} onDismiss={onClose} />
          ))}
        </ScrollView>
        <Animated.View pointerEvents="box-none" style={[{ position: 'absolute', top: insets.top + 8, left: 12, right: 12,
          flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, chrome]}>
          <IconButton icon="close" label="Закрыть" onPress={onClose} kind="glass" color="#fff" />
          {urls.length > 1 ? <Txt v="subhead" color="#fff" style={{ fontFamily: 'Onest_600SemiBold' }}>{page + 1} из {urls.length}</Txt> : null}
          <View style={{ width: 44 }} />
        </Animated.View>
      </GestureHandlerRootView>
    </>
  );
}

function ZoomImage({ uri, w, h, active, dragY, onZoom, onDismiss }: {
  uri: string; w: number; h: number; active: boolean; dragY: SharedValue<number>; onZoom: (z: boolean) => void; onDismiss: () => void;
}) {
  const scale = useSharedValue(1);
  const saved = useSharedValue(1);
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const sx = useSharedValue(0);
  const sy = useSharedValue(0);
  const [zoomed, setZoomed] = useState(false);
  const report = (z: boolean) => { setZoomed(z); onZoom(z); };

  // Ушли на другое фото — это возвращаем к исходному виду
  useEffect(() => {
    if (active) return;
    scale.set(1); saved.set(1); tx.set(0); ty.set(0); sx.set(0); sy.set(0);
  }, [active, scale, saved, tx, ty, sx, sy]);

  const clampT = (v: number, s: number, side: number) => {
    'worklet';
    const max = (side * s - side) / 2;
    return Math.min(max, Math.max(-max, v));
  };
  const reset = () => {
    'worklet';
    scale.set(withTiming(1)); saved.set(1);
    tx.set(withTiming(0)); ty.set(withTiming(0)); sx.set(0); sy.set(0);
    scheduleOnRN(report, false);
  };

  const pinch = Gesture.Pinch()
    .onUpdate((e) => { scale.set(Math.min(MAX, Math.max(1, saved.get() * e.scale))); })
    .onEnd(() => {
      if (scale.get() < 1.05) { reset(); return; }
      saved.set(scale.get());
      tx.set(withTiming(clampT(tx.get(), scale.get(), w))); ty.set(withTiming(clampT(ty.get(), scale.get(), h)));
      sx.set(clampT(tx.get(), scale.get(), w)); sy.set(clampT(ty.get(), scale.get(), h));
      scheduleOnRN(report, true);
    });

  // Без зума — тянем вниз/вверх, чтобы закрыть (горизонталь отдаём листанию); с зумом — двигаем фото
  const pan = (zoomed && active ? Gesture.Pan() : Gesture.Pan().activeOffsetY([-12, 12]).failOffsetX([-12, 12]))
    .averageTouches(true)
    .onUpdate((e) => {
      if (saved.get() > 1) { tx.set(sx.get() + e.translationX); ty.set(sy.get() + e.translationY); }
      else dragY.set(e.translationY);
    })
    .onEnd((e) => {
      if (saved.get() > 1) {
        sx.set(clampT(tx.get(), saved.get(), w)); sy.set(clampT(ty.get(), saved.get(), h));
        tx.set(withTiming(sx.get())); ty.set(withTiming(sy.get()));
      } else if (Math.abs(e.translationY) > 120 || Math.abs(e.velocityY) > 900) {
        scheduleOnRN(onDismiss);
      } else dragY.set(withTiming(0));
    });

  const doubleTap = Gesture.Tap().numberOfTaps(2).onEnd((e) => {
    if (saved.get() > 1) { reset(); return; }
    saved.set(DOUBLE); scale.set(withTiming(DOUBLE));
    // Приближаем к точке тапа
    sx.set(clampT((w / 2 - e.x) * (DOUBLE - 1), DOUBLE, w)); sy.set(clampT((h / 2 - e.y) * (DOUBLE - 1), DOUBLE, h));
    tx.set(withTiming(sx.get())); ty.set(withTiming(sy.get()));
    scheduleOnRN(report, true);
  });

  const style = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.get() }, { translateY: ty.get() + (saved.get() > 1 ? 0 : dragY.get()) }, { scale: scale.get() }],
  }));

  return (
    <GestureDetector gesture={Gesture.Simultaneous(pinch, pan, doubleTap)}>
      <Animated.View style={[{ width: w, height: h }, style]}>
        <Image source={uri} contentFit="contain" transition={150} style={{ width: w, height: h }} accessibilityLabel="Фото" />
      </Animated.View>
    </GestureDetector>
  );
}
