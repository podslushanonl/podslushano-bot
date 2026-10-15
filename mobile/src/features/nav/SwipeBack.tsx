import { ReactNode } from 'react';
import { Platform, useWindowDimensions } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, { interpolate, useAnimatedStyle, useSharedValue, withSpring, withTiming } from 'react-native-reanimated';
import { scheduleOnRN } from 'react-native-worklets';

const EDGE = 28;   // ширина зоны у левого края, откуда начинается жест (как в iOS)

/** Свайп от левого края вправо — назад, как в iOS. В приложении это делает сам iOS (native-stack),
 *  а в браузере и PWA на iPhone жеста нет — его даёт эта обёртка: экран едет за пальцем, под ним виден
 *  предыдущий; отпустили дальше трети ширины или быстрым движением — возвращаемся назад. */
export function SwipeBack({ enabled, onBack, bg, children }: { enabled: boolean; onBack: () => void; bg: string; children: ReactNode }) {
  const { width } = useWindowDimensions();
  const x = useSharedValue(0);
  const pan = Gesture.Pan()
    .enabled(enabled)
    .hitSlop({ left: 0, width: EDGE })
    .activeOffsetX(10)
    .failOffsetY([-14, 14])
    .onUpdate((e) => { x.set(Math.max(0, e.translationX)); })
    .onEnd((e) => {
      if (x.get() > width / 3 || e.velocityX > 700) {
        x.set(withTiming(width, { duration: 180 }, (done) => { if (done) scheduleOnRN(onBack); }));
      } else {
        x.set(withSpring(0, { damping: 22, stiffness: 260 }));
      }
    });
  const style = useAnimatedStyle(() => ({
    transform: [{ translateX: x.get() }],
    shadowOpacity: interpolate(x.get(), [0, width], [0.25, 0]),
  }));
  return (
    <GestureDetector gesture={pan}>
      <Animated.View style={[{ flex: 1, backgroundColor: bg, shadowColor: '#000000', shadowRadius: 18, shadowOffset: { width: -4, height: 0 } }, style]}>
        {children}
      </Animated.View>
    </GestureDetector>
  );
}

export const WEB = Platform.OS === 'web';
