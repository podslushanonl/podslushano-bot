// Дизайн-система podslushano.nl «Dutch Modern Editorial»: цвета светлой и тёмной темы, сетка 8pt,
// скругления и типографика на системных шрифтах (San Francisco на iOS, Roboto на Android).
// Имена из ТЗ: background → bg, surface → bgElevated, primary → accent, secondary → secondary,
// textPrimary → ink, textSecondary → muted, border → line.

export const palette = {
  light: {
    bg: '#F8F9FA',            // background
    bgElevated: '#FFFFFF',    // surface: карточки
    bgSunken: '#F1F3F5',
    ink: '#111827',           // textPrimary
    text: '#1F2937',
    muted: '#6B7280',         // textSecondary
    faint: '#9CA3AF',
    line: '#E5E7EB',          // border, 1px
    lineStrong: '#D1D5DB',
    accent: '#FF5A1F',        // primary: Dutch Orange — кнопки, активные вкладки, бейджи
    accentSoft: '#FFF1EB',
    onAccent: '#FFFFFF',
    accentText: '#C2410C',    // оранжевый для текста на светлом фоне (контраст 4,5:1)
    secondary: '#0066CC',     // Tulip Blue — ссылки, теги городов, статус NS
    secondarySoft: '#E6F0FA',
    success: '#10B981',
    danger: '#EF4444',
    info: '#0066CC',
    glassFill: 'rgba(255,255,255,0.72)',
    glassFillStrong: 'rgba(255,255,255,0.9)',
    glassStroke: 'rgba(255,255,255,0.75)',
    glassEdge: 'rgba(17,24,39,0.08)',
    glassShadow: 'rgba(17,24,39,0.16)',
    scrim: 'rgba(17,24,39,0.4)',
    inverse: '#111827',
    onInverse: '#FFFFFF',
    onInverseMuted: '#D1D5DB',
    placeholder: '#E5E7EB',
    hero: '#FFFFFF',
    heroInner: '#F8F9FA',
    heroInner2: '#F1F3F5',
    onHero: '#111827',
    onHeroMuted: '#6B7280',
    segTrack: '#EEF0F2',
    segOn: '#FFFFFF',
    iconOff: '#6B7280',       // неактивные вкладки нижнего меню
  },
  dark: {
    bg: '#0F1115',
    bgElevated: '#1A1D24',
    bgSunken: '#232730',
    ink: '#F3F4F6',
    text: '#E5E7EB',
    muted: '#9CA3AF',
    faint: '#6B7280',
    line: '#2A2E39',
    lineStrong: '#3A3F4B',
    accent: '#FF5A1F',
    accentSoft: '#3A2116',
    onAccent: '#FFFFFF',
    accentText: '#FF8A5C',
    secondary: '#4DA3FF',     // Tulip Blue светлее: на тёмном фоне #0066CC не читается
    secondarySoft: '#14273D',
    success: '#10B981',
    danger: '#EF4444',
    info: '#4DA3FF',
    glassFill: 'rgba(26,29,36,0.72)',
    glassFillStrong: 'rgba(26,29,36,0.9)',
    glassStroke: 'rgba(255,255,255,0.12)',
    glassEdge: 'rgba(255,255,255,0.08)',
    glassShadow: 'rgba(0,0,0,0.45)',
    scrim: 'rgba(0,0,0,0.55)',
    inverse: '#2A2E39',
    onInverse: '#FFFFFF',
    onInverseMuted: '#9CA3AF',
    placeholder: '#232730',
    hero: '#1A1D24',
    heroInner: '#232730',
    heroInner2: '#2A2E39',
    onHero: '#F3F4F6',
    onHeroMuted: '#9CA3AF',
    segTrack: '#1A1D24',
    segOn: '#2A2E39',
    iconOff: '#9CA3AF',
  },
} as const;

export type Colors = { [K in keyof (typeof palette)['light']]: string };

// Скругления: карточки 16, кнопки и поля 12, теги и чипы 999
export const radius = { xs: 8, s: 12, m: 12, l: 16, xl: 16, xxl: 20, pill: 999, card: 16, control: 12 } as const;
/** Рамка карточек — 1px. */
export const HAIRLINE = 1;
// Сетка 8pt. screen — горизонтальный отступ экрана, gap — отступ между карточками
export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24, xxl: 32, xxxl: 40, screen: 16, gap: 12 } as const;
/** Минимальная зона нажатия (Apple HIG, Material). */
export const TOUCH = 44;

// Системный шрифт: семейство не задаём, меняется только насыщенность
type W = '400' | '500' | '600' | '700' | '800';
const w = (fontWeight: W) => ({ fontWeight });
export const fonts = {
  display: w('800'), displaySemi: w('700'), regular: w('400'), medium: w('500'), semibold: w('600'), bold: w('700'),
} as const;

export const type = {
  display: { ...fonts.display, fontSize: 30, lineHeight: 36, letterSpacing: -0.4 },
  title1: { ...fonts.display, fontSize: 26, lineHeight: 32, letterSpacing: -0.4 },
  title2: { ...fonts.bold, fontSize: 20, lineHeight: 26, letterSpacing: -0.2 },
  title3: { ...fonts.bold, fontSize: 18, lineHeight: 24, letterSpacing: -0.2 },
  headline: { ...fonts.semibold, fontSize: 16, lineHeight: 22 },
  body: { ...fonts.regular, fontSize: 16, lineHeight: 24 },
  bodyStrong: { ...fonts.semibold, fontSize: 16, lineHeight: 22 },
  callout: { ...fonts.regular, fontSize: 15, lineHeight: 21 },
  subhead: { ...fonts.medium, fontSize: 14, lineHeight: 20 },
  footnote: { ...fonts.regular, fontSize: 13, lineHeight: 18 },
  caption: { ...fonts.medium, fontSize: 12, lineHeight: 16 },
  overline: { ...fonts.bold, fontSize: 11, lineHeight: 14, letterSpacing: 0.8, textTransform: 'uppercase' as const },
  price: { ...fonts.bold, fontSize: 17, lineHeight: 22, letterSpacing: -0.2 },
} as const;

export type TypeVariant = keyof typeof type;
