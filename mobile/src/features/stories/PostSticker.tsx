import { View } from 'react-native';
import { postPhoto } from '@/api/feed';
import type { StoryPost } from '@/api/stories';
import { Avatar, Icon, Img, Txt, VerifiedBadge } from '@/ui';

/** Пост как наклейка в истории (как «поделиться публикацией» в Instagram): белая карточка с автором, фото и текстом. */
export function PostSticker({ post, width }: { post: StoryPost; width: number }) {
  if (!post) {
    return (
      <View style={{ width, padding: 18, borderRadius: 18, backgroundColor: 'rgba(255,255,255,0.92)', alignItems: 'center', gap: 6 }}>
        <Icon name="lock" size={22} color="#666666" />
        <Txt v="subhead" color="#1A1A1A" center>Публикация недоступна</Txt>
      </View>
    );
  }
  return (
    <View style={{ width, borderRadius: 18, backgroundColor: '#FFFFFF', overflow: 'hidden',
      boxShadow: '0 12px 32px rgba(0,0,0,0.28)' } as any}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 12, paddingVertical: 10 }}>
        <Avatar name={post.author.name} id={post.author.id} uri={post.author.avatar} size={30} />
        <Txt v="subhead" color="#1A1A1A" numberOfLines={1} style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }}>{post.author.name}</Txt>
        {post.author.verified ? <VerifiedBadge size={14} /> : null}
      </View>
      {post.photo ? (
        <Img source={postPhoto(post.photo)} contentFit="cover"
          style={{ width: '100%', aspectRatio: post.ratio > 1.2 ? 16 / 9 : post.ratio < 0.9 ? 4 / 5 : 1 }} />
      ) : null}
      {post.text ? (
        <Txt v={post.photo ? 'footnote' : 'callout'} color="#1A1A1A" numberOfLines={post.photo ? 3 : 8}
          style={{ paddingHorizontal: 12, paddingTop: 10, paddingBottom: 12 }}>{post.text}</Txt>
      ) : <View style={{ height: 10 }} />}
    </View>
  );
}
