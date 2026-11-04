import { Redirect } from 'expo-router';

/** Старый адрес настроек: всё перенесено в профиль. */
export default function Settings() {
  return <Redirect href="/profile" />;
}
