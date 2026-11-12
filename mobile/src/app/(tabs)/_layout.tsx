import AppTabs from '@/features/nav/AppTabs';
import { useProvince } from '@/lib/province';

/** Гостевой режим: разделы открываются сразу, без регистрации и без обязательного выбора города. */
export default function TabsLayout() {
  const { ready } = useProvince();
  if (!ready) return null;
  return <AppTabs />;
}
