import { Redirect } from 'expo-router';
import AppTabs from '@/features/nav/AppTabs';
import { useProvince } from '@/lib/province';

/** Разделы открываются, когда провинция выбрана; при первом запуске — приветствие и выбор провинции. */
export default function TabsLayout() {
  const { province, ready } = useProvince();
  if (!ready) return null;
  if (!province) return <Redirect href="/welcome" />;
  return <AppTabs />;
}
