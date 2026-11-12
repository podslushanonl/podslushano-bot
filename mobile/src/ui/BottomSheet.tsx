import { BottomSheetBackdrop, BottomSheetBackdropProps, BottomSheetModal, BottomSheetView } from '@gorhom/bottom-sheet';
import { ReactNode, useCallback, useEffect, useRef } from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { radius, space, useTheme } from '@/theme';
import { Txt } from './Text';

/**
 * Шторка снизу (@gorhom/bottom-sheet): высота по содержимому, закрывается свайпом вниз или нажатием на фон.
 * Управляется пропсом visible; onClose вызывается при любом закрытии.
 */
export function BottomSheetWrapper({ visible, onClose, title, children }: {
  visible: boolean; onClose: () => void; title?: string; children: ReactNode;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const ref = useRef<BottomSheetModal>(null);
  const shown = useRef(false);
  useEffect(() => {
    if (visible && !shown.current) { shown.current = true; ref.current?.present(); }
    if (!visible && shown.current) { shown.current = false; ref.current?.dismiss(); }
  }, [visible]);
  const backdrop = useCallback((p: BottomSheetBackdropProps) => (
    <BottomSheetBackdrop {...p} appearsOnIndex={0} disappearsOnIndex={-1} opacity={0.45} pressBehavior="close" />
  ), []);
  return (
    <BottomSheetModal ref={ref} onDismiss={() => { shown.current = false; onClose(); }} enableDynamicSizing enablePanDownToClose backdropComponent={backdrop}
      backgroundStyle={{ backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xxl, borderTopRightRadius: radius.xxl }}
      handleIndicatorStyle={{ backgroundColor: c.lineStrong, width: 40 }}>
      <BottomSheetView style={{ paddingHorizontal: space.screen, paddingTop: 4, paddingBottom: insets.bottom + space.l, gap: space.gap }}>
        {title ? <Txt v="title2" accessibilityRole="header">{title}</Txt> : null}
        <View style={{ gap: space.gap }}>{children}</View>
      </BottomSheetView>
    </BottomSheetModal>
  );
}
