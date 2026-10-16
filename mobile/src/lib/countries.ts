// Страны приложения. Названия — ровно как на сервере (там они строго проверяются).
export const COUNTRIES = ['Нидерланды', 'Германия', 'Бельгия'] as const;
export type Country = (typeof COUNTRIES)[number];
export const DEFAULT_COUNTRY: Country = 'Нидерланды';

export const asCountry = (v?: string | null): Country => (COUNTRIES as readonly string[]).includes(v || '') ? (v as Country) : DEFAULT_COUNTRY;
