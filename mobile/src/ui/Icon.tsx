import { SymbolView } from 'expo-symbols';
import type { ColorValue } from 'react-native';
import { useTheme } from '@/theme';

// Системные иконки: SF Symbols на iPhone, Material Symbols на Android и в браузере. Без эмодзи.
const I = {
  home: ['house', 'home'], homeFill: ['house.fill', 'home'],
  market: ['bag', 'shopping_bag'], marketFill: ['bag.fill', 'shopping_bag'],
  chat: ['bubble.left.and.bubble.right', 'forum'], chatFill: ['bubble.left.and.bubble.right.fill', 'forum'],
  bubble: ['bubble.left', 'chat_bubble'],
  person: ['person.crop.circle', 'account_circle'], personFill: ['person.crop.circle.fill', 'account_circle'],
  search: ['magnifyingglass', 'search'],
  bell: ['bell', 'notifications'],
  plus: ['plus', 'add'],
  close: ['xmark', 'close'],
  back: ['chevron.left', 'arrow_back_ios_new'],
  chevron: ['chevron.right', 'chevron_right'],
  down: ['chevron.down', 'expand_more'],
  location: ['mappin.and.ellipse', 'location_on'],
  ticket: ['ticket', 'confirmation_number'],
  train: ['tram.fill', 'train'],
  tag: ['tag', 'sell'],
  calendar: ['calendar', 'calendar_month'],
  clock: ['clock', 'schedule'],
  heart: ['heart', 'favorite'], heartFill: ['heart.fill', 'favorite'],
  share: ['square.and.arrow.up', 'ios_share'],
  more: ['ellipsis', 'more_horiz'],
  filter: ['line.3.horizontal.decrease', 'tune'],
  camera: ['camera', 'photo_camera'],
  photo: ['photo', 'image'],
  send: ['arrow.up', 'arrow_upward'],
  phone: ['phone', 'call'],
  mail: ['envelope', 'mail'],
  globe: ['globe', 'language'],
  shield: ['checkmark.shield.fill', 'verified_user'],
  check: ['checkmark', 'check'],
  warning: ['exclamationmark.triangle', 'warning'],
  edit: ['pencil', 'edit'],
  trash: ['trash', 'delete'],
  flag: ['flag', 'flag'],
  block: ['hand.raised', 'block'],
  logout: ['rectangle.portrait.and.arrow.right', 'logout'],
  briefcase: ['briefcase', 'work'],
  gift: ['gift', 'redeem'],
  car: ['car', 'directions_car'],
  box: ['shippingbox', 'inventory_2'],
  house: ['house', 'home'],
  cloud: ['cloud', 'cloud'], sun: ['sun.max', 'light_mode'], rain: ['cloud.rain', 'rainy'],
  euro: ['eurosign.circle', 'euro'],
  sparkles: ['sparkles', 'auto_awesome'],
  newspaper: ['newspaper', 'newspaper'],
  info: ['info.circle', 'info'],
  settings: ['gearshape', 'settings'],
  route: ['point.topleft.down.to.point.bottomright.curvepath', 'route'],
  arrowRight: ['arrow.right', 'arrow_forward'],
  people: ['person.2', 'group'],
  lock: ['lock', 'lock'],
  repost: ['arrow.2.squarepath', 'repeat'],
  grid: ['square.grid.3x3', 'grid_view'],
  text: ['text.alignleft', 'notes'],
  link: ['link', 'link'],
} as const;

export type IconName = keyof typeof I;

export function Icon({ name, size = 22, color }: { name: IconName; size?: number; color?: ColorValue }) {
  const { c } = useTheme();
  const [ios, md] = I[name];
  return <SymbolView name={{ ios, android: md, web: md } as any} size={size} tintColor={color ?? c.ink} />;
}
