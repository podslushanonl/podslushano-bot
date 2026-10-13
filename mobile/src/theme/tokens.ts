// Дизайн-система podslushano: цвета светлой и тёмной темы, радиусы, отступы, типографика.
// Liquid Glass: основная поверхность — светлое стекло поверх живого контента, акцент — фирменный оранжевый.

export const palette = {
  light: {
    bg: '#F2F3F5',
    bgElevated: '#FFFFFF',
    bgSunken: '#E9EBEF',
    ink: '#0B0D12',
    text: '#2B313B',
    muted: '#5F6672',
    faint: '#9AA0AA',
    line: 'rgba(11,13,18,0.08)',
    lineStrong: 'rgba(11,13,18,0.14)',
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
    inverse: '#0B0D12',
    onInverse: '#FFFFFF',
    onInverseMuted: '#C4C9D2',
    placeholder: '#DCE0E6',
    // тёмные «витринные» карточки (Сейчас, Сэкономить, ваш город) — тёмные в обеих темах
    hero: '#0B0D12',
    heroInner: '#1C2029',
    heroInner2: '#2A2F3A',
    onHero: '#FFFFFF',
    onHeroMuted: '#C4C9D2',
    segTrack: '#E6E8EC',
    segOn: '#FFFFFF',
  },
  dark: {
    bg: '#0A0B0E',
    bgElevated: '#16181D',
    bgSunken: '#1E2128',
    ink: '#F4F5F7',
    text: '#D3D7DE',
    muted: '#979DA8',
    faint: '#646A75',
    line: 'rgba(255,255,255,0.08)',
    lineStrong: 'rgba(255,255,255,0.16)',
    accent: '#FF6A33',
    accentSoft: '#3A1D10',
    onAccent: '#0B0D12',
    accentText: '#FF9466',
    success: '#4ADE80',
    danger: '#F87171',
    info: '#60A5FA',
    glassFill: 'rgba(28,30,36,0.58)',
    glassFillStrong: 'rgba(28,30,36,0.80)',
    glassStroke: 'rgba(255,255,255,0.16)',
    glassEdge: 'rgba(255,255,255,0.10)',
    glassShadow: 'rgba(0,0,0,0.45)',
    scrim: 'rgba(0,0,0,0.55)',
    inverse: '#F4F5F7',
    onInverse: '#0B0D12',
    onInverseMuted: '#4B5260',
    placeholder: '#23262D',
    hero: '#1B1E25',
    heroInner: '#262A33',
    heroInner2: '#323743',
    onHero: '#FFFFFF',
    onHeroMuted: '#AEB4BF',
    segTrack: '#16181D',
    segOn: '#2C3039',
  },
} as const;

export type Colors = { [K in keyof (typeof palette)['light']]: string };

export const radius = { xs: 8, s: 12, m: 16, l: 22, xl: 28, xxl: 34, pill: 999 } as const;
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
