import { createContext, ReactNode, useContext, useMemo } from 'react';
import { useColorScheme, type ViewStyle } from 'react-native';
import { Colors, palette } from './tokens';

export * from './tokens';

/** shadow — мягкая тень карточек в светлой теме (на светлом фоне одной тонкой рамки мало); в тёмной теме объём даёт слой и рамка. */
type Theme = { c: Colors; dark: boolean; shadow: ViewStyle };
const LIGHT_SHADOW = { boxShadow: '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)' } as ViewStyle;
const Ctx = createContext<Theme>({ c: palette.light, dark: false, shadow: LIGHT_SHADOW });

/** Тема по системной настройке телефона: светлая или тёмная, меняется на лету. */
export function ThemeRoot({ children }: { children: ReactNode }) {
  const scheme = useColorScheme();
  const value = useMemo<Theme>(() => (scheme === 'dark'
    ? { c: palette.dark, dark: true, shadow: {} }
    : { c: palette.light, dark: false, shadow: LIGHT_SHADOW }), [scheme]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
