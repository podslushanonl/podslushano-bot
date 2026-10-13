import { SymbolView } from 'expo-symbols';
import type { ColorValue } from 'react-native';

type Icon = { ios: string; android: string; web: string };
const ICONS: Record<string, Icon> = {
  housing: { ios: 'house.fill', android: 'home', web: 'home' },
  goods: { ios: 'bag.fill', android: 'shopping_bag', web: 'shopping_bag' },
  free: { ios: 'gift.fill', android: 'redeem', web: 'redeem' },
  jobs: { ios: 'briefcase.fill', android: 'work', web: 'work' },
  rides: { ios: 'car.fill', android: 'directions_car', web: 'directions_car' },
  other: { ios: 'shippingbox.fill', android: 'inventory_2', web: 'inventory_2' },
  phone: { ios: 'phone.fill', android: 'call', web: 'call' },
  email: { ios: 'envelope.fill', android: 'mail', web: 'mail' },
  website: { ios: 'globe', android: 'language', web: 'language' },
  photo: { ios: 'camera.fill', android: 'photo_camera', web: 'photo_camera' },
};

/** Иконка категории барахолки или способа связи (системные символы, не эмодзи). */
export function MarketIcon({ name, color, size = 22 }: { name: string; color: ColorValue; size?: number }) {
  return <SymbolView name={(ICONS[name] || ICONS.other) as any} tintColor={color} size={size} />;
}
