import { useLocalSearchParams } from 'expo-router';
import { ProfileView } from '@/features/profile/ProfileView';

/** Страница другого человека — тот же вид, что и мой профиль, с кнопками дружбы и сообщений. */
export default function UserProfile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <ProfileView userId={Number(id)} />;
}
