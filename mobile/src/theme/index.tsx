import { createContext, ReactNode, useContext } from 'react';
import { Colors, palette } from './tokens';

export * from './tokens';

type Theme = { c: Colors; dark: boolean };
// Приложение всегда в тёмной теме (как Threads): единые слои без «зебры» белых карточек при светлой теме телефона.
const DARK: Theme = { c: palette.dark, dark: true };
const Ctx = createContext<Theme>(DARK);

export function ThemeRoot({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={DARK}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
