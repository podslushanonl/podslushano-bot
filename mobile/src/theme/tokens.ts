// Дизайн-система podslushano: цвета светлой и тёмной темы, радиусы, отступы, типографика.
// Liquid Glass: основная поверхность — светлое стекло поверх живого контента, акцент — фирменный оранжевый.

export const palette = {
  // Светлая тема: светло-серый фон, белые карточки с мягкой рамкой #E0E0E0, глубокий тёмный текст
  light: {
    bg: '#F5F5F5',
    bgElevated: '#FFFFFF',
    bgSunken: '#EFEFEF',
    ink: '#1A1A1A',
    text: '#2B2B2B',
    muted: '#666666',
    faint: '#9A9A9A',
    line: '#E0E0E0',
    lineStrong: '#CFCFCF',
    accent: '#FF5A1F',
    accentSoft: '#FFE9DF',
    onAccent: '#0B0D12',
    accentText: '#C2410C',
    success: '#1F7A4D',
    danger: '#C0262D',
    info: '#2563EB',
    // стекло
    glassFill: 'rgba(255,255,255,0.64)',
    glassFillStrong: 'rgba(255,255,255,0.82)',
    glassStroke: 'rgba(255,255,255,0.75)',
    glassEdge: 'rgba(11,13,18,0.08)',
    glassShadow: 'rgba(17,24,39,0.16)',
    scrim: 'rgba(11,13,18,0.38)',
    inverse: '#1A1A1A',
    onInverse: '#FFFFFF',
    onInverseMuted: '#C4C4C4',
    placeholder: '#E8E8E8',
    // «витринные» карточки (Сейчас, Сэкономить, вход) — в светлой теме тоже светлые, без контрастных чёрных плашек
    hero: '#FFFFFF',
    heroInner: '#F5F5F5',
    heroInner2: '#EBEBEB',
    onHero: '#1A1A1A',
    onHeroMuted: '#666666',
    segTrack: '#EBEBEB',
    segOn: '#FFFFFF',
    iconOff: '#8E8E8E',   // неактивные вкладки нижнего меню
  },
  dark: {
    // Слои как в Threads: графитовый фон, карточки на тон светлее, тонкая рамка #2E2E2E — без «мёртвого» чёрного
    bg: '#121212',
    bgElevated: '#1E1E1E',
    bgSunken: '#262626',
    ink: '#FFFFFF',
    text: '#E6E6E6',
    muted: '#A0A0A0',
    faint: '#6E6E6E',
    line: '#2E2E2E',
    lineStrong: '#3A3A3A',
    accent: '#FF6A33',
    accentSoft: '#3A1D10',
    onAccent: '#0B0D12',
    accentText: '#FF9466',
    success: '#4ADE80',
    danger: '#F87171',
    info: '#60A5FA',
    glassFill: 'rgba(30,30,30,0.62)',
    glassFillStrong: 'rgba(30,30,30,0.84)',
    glassStroke: 'rgba(255,255,255,0.12)',
    glassEdge: 'rgba(255,255,255,0.08)',
    glassShadow: 'rgba(0,0,0,0.45)',
    scrim: 'rgba(0,0,0,0.55)',
    // «Сильная» поверхность в тёмной теме — графит, а не белый: без контрастных белых плашек
    inverse: '#2E2E2E',
    onInverse: '#FFFFFF',
    onInverseMuted: '#A0A0A0',
    placeholder: '#262626',
    hero: '#1E1E1E',
    heroInner: '#272727',
    heroInner2: '#323232',
    onHero: '#FFFFFF',
    onHeroMuted: '#AEB4BF',
    segTrack: '#1E1E1E',
    segOn: '#2E2E2E',
    iconOff: '#666666',   // неактивные вкладки нижнего меню
  },
} as const;

export type Colors = { [K in keyof (typeof palette)['light']]: string };

export const radius = { xs: 8, s: 12, m: 16, l: 22, xl: 28, xxl: 34, pill: 999 } as const;
/** Тонкая рамка карточек: даёт объём слоям, не перегружая. */
export const HAIRLINE = 0.5;
export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 20, xxl: 28, xxxl: 40 } as const;

export const fonts = {
  display: 'Unbounded_700Bold',
  displaySemi: 'Unbounded_600SemiBold',
  regular: 'Onest_400Regular',
  medium: 'Onest_500Medium',
  semibold: 'Onest_600SemiBold',
  bold: 'Onest_700Bold',
} as const;

export const type = {
  display: { fontFamily: fonts.display, fontSize: 32, lineHeight: 37, letterSpacing: -0.6 },
  title1: { fontFamily: fonts.display, fontSize: 26, lineHeight: 31, letterSpacing: -0.4 },
  title2: { fontFamily: fonts.displaySemi, fontSize: 20, lineHeight: 25, letterSpacing: -0.2 },
  title3: { fontFamily: fonts.bold, fontSize: 19, lineHeight: 24, letterSpacing: -0.2 },
  headline: { fontFamily: fonts.bold, fontSize: 17, lineHeight: 22 },
  body: { fontFamily: fonts.regular, fontSize: 16, lineHeight: 23 },
  bodyStrong: { fontFamily: fonts.semibold, fontSize: 16, lineHeight: 22 },
  callout: { fontFamily: fonts.medium, fontSize: 15, lineHeight: 20 },
  subhead: { fontFamily: fonts.medium, fontSize: 14, lineHeight: 19 },
  footnote: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 17 },
  caption: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 16 },
  overline: { fontFamily: fonts.bold, fontSize: 11.5, lineHeight: 14, letterSpacing: 0.9, textTransform: 'uppercase' as const },
  price: { fontFamily: fonts.display, fontSize: 17, lineHeight: 21, letterSpacing: -0.2 },
} as const;

export type TypeVariant = keyof typeof type;
