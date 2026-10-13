import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button, Card, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { logout, saveProfile, useAuth } from '@/lib/auth';

const CITIES = ['Amsterdam', 'Rotterdam', 'Den Haag', 'Utrecht', 'Eindhoven', 'Groningen', 'Tilburg', 'Almere', 'Breda', 'Nijmegen', 'Arnhem', 'Haarlem', 'Maastricht', 'Leiden', 'Zwolle'];

export default function Profile() {
  const { user, favorites } = useAuth();
  const [name, setName] = useState(user?.name || '');
  const [city, setCity] = useState(user?.city || '');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  if (!user) return <View style={{ padding: 20, gap: 12 }}><P muted>Вы не вошли.</P><Button title="Войти" onPress={() => router.replace('/login')} /></View>;

  const save = async () => {
    setBusy(true); setMsg('');
    try { await saveProfile({ name: name.trim(), city: city.trim() }); setMsg('Сохранено'); router.back(); }
    catch (e: any) { setMsg(e?.message || 'Не удалось сохранить'); } finally { setBusy(false); }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }} keyboardShouldPersistTaps="handled">
      <Eyebrow>Мой podslushano</Eyebrow>
      <H size={26}>Профиль</H>
      <Card>
        <Text style={st.label}>Как вас зовут</Text>
        <TextInput value={name} onChangeText={setName} placeholder="Имя" placeholderTextColor={C.muted} style={st.input} maxLength={80} />
        <Text style={st.label}>Ваш город</Text>
        <TextInput value={city} onChangeText={setCity} placeholder="Например, Utrecht" placeholderTextColor={C.muted} style={st.input} maxLength={80} />
        <View style={st.chips}>
          {CITIES.map((c) => (
            <Pressable key={c} onPress={() => setCity(c)} style={[st.chip, city === c && st.chipOn]}>
              <Text style={[st.chipT, city === c && { color: '#fff' }]}>{c}</Text>
            </Pressable>
          ))}
        </View>
        <Button title={busy ? 'Сохраняем…' : 'Сохранить'} onPress={save} />
        {msg ? <P muted>{msg}</P> : null}
      </Card>
      <Card>
        <Eyebrow color={C.muted}>Аккаунт</Eyebrow>
        <P>{user.email ? `Почта: ${user.email}` : 'Вход через Telegram'}</P>
        <P muted>В избранном: {favorites.length}</P>
      </Card>
      <Button title="Выйти" soft onPress={async () => { await logout(); router.replace('/(tabs)/more'); }} />
    </ScrollView>
  );
}

const st = StyleSheet.create({
  label: { fontSize: 13, fontWeight: '700', color: C.muted, marginTop: 4 },
  input: { backgroundColor: C.bg, borderRadius: 14, borderWidth: 1, borderColor: C.line, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: C.ink },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: C.bg, borderWidth: 1, borderColor: C.line },
  chipOn: { backgroundColor: C.accent, borderColor: C.accent },
  chipT: { fontSize: 13, fontWeight: '600', color: C.ink },
});
