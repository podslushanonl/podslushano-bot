import { router } from 'expo-router';
import { View } from 'react-native';
import { newsSlug } from '@/api/daily';
import { News } from '@/api/content';
import { ago } from '@/lib/format';
import { radius, useTheme } from '@/theme';
import { Icon, Img, Tap, Txt } from '@/ui';

/** Строка новости: фото, заголовок, когда. local — новость из провинции человека. */
export function NewsRow({ n, local }: { n: News; local?: boolean }) {
  const { c } = useTheme();
  const img = n.thumb || n.img;
  return (
    <Tap onPress={() => router.push({ pathname: '/news/[slug]', params: { slug: newsSlug(n) } })} scaleTo={0.985}
      accessibilityLabel={n.h} style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
      {img ? <Img source={img} style={{ width: 84, height: 64, borderRadius: radius.m }} accessibilityIgnoresInvertColors /> : (
        <View style={{ width: 84, height: 64, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="newspaper" size={24} color={c.accentText} />
        </View>
      )}
      <View style={{ flex: 1, gap: 3 }}>
        <Txt v="headline" numberOfLines={3}>{n.h}</Txt>
        <Txt v="footnote" tone={local ? 'accent' : 'muted'}>{[local ? 'Ваша провинция' : '', ago(n.date, n.time)].filter(Boolean).join(' · ')}</Txt>
      </View>
    </Tap>
  );
}
