import { Redirect } from 'expo-router';

/** Старый адрес афиши (ссылки из уведомлений прежних версий) ведёт на вкладку «События». */
export default function AfishaRedirect() {
  return <Redirect href="/events" />;
}
