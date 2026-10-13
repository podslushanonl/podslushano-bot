import { createContext, ReactNode, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';
import { Colors, palette } from './tokens';

export * from './tokens';

type Theme = { c: Colors; dark: boolean };
const Ctx = createContext<Theme>({ c: palette.light, dark: false });

/** Тема по системной настройке телефона (светлая / тёмная). */
export function ThemeRoot({ children }: { children: ReactNode }) {
  const scheme = useColorScheme();
  const value = useMemo<Theme>(() => ({ c: scheme === 'dark' ? palette.dark : palette.light, dark: scheme === 'dark' }), [scheme]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
