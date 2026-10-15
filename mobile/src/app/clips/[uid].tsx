import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useUserClips } from '@/api/pulse';
import { ClipFeed } from '@/features/pulse/ClipFeed';
import { IconButton } from '@/ui';

/** Видео человека из вкладки Pulse в профиле: та же полноэкранная лента, с того ролика, по которому нажали. */
export default function UserClips() {
  const { uid, start } = useLocalSearchParams<{ uid: string; start?: string }>();
  const insets = useSafeAreaInsets();
  const q = useUserClips(Number(uid));
  const clips = q.data || [];
  const at = Math.max(0, clips.findIndex((c) => String(c.id) === start));
  return (
    <View style={{ flex: 1, backgroundColor: '#000000' }}>
      {q.data ? (
        <ClipFeed key={at} clips={clips} initialIndex={at} bottom={insets.bottom} />
      ) : null}
      <View style={{ position: 'absolute', top: insets.top + 6, left: 8 }}>
        <IconButton icon="back" label="Назад" kind="plain" color="#FFFFFF" onPress={() => (router.canGoBack() ? router.back() : router.replace('/pulse'))} />
      </View>
    </View>
  );
}
