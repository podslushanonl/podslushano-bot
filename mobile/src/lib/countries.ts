// Страны приложения. Названия — ровно как на сервере (там они строго проверяются).
export const COUNTRIES = ['Нидерланды', 'Германия', 'Бельгия'] as const;
export type Country = (typeof COUNTRIES)[number];
export const DEFAULT_COUNTRY: Country = 'Нидерланды';

// Города — как пишут в самой стране, латиницей
export const CITIES_BY_COUNTRY: Record<Country, string[]> = {
  Нидерланды: ['Amsterdam', 'Rotterdam', 'Den Haag', 'Utrecht', 'Eindhoven', 'Groningen', 'Tilburg', 'Almere', 'Breda',
    'Nijmegen', 'Arnhem', 'Haarlem', 'Leiden', 'Maastricht', 'Zwolle', 'Amersfoort', 'Delft', 'Enschede', 'Den Bosch', 'Oss'],
  Германия: ['Berlin', 'München', 'Hamburg', 'Köln', 'Frankfurt am Main', 'Düsseldorf', 'Stuttgart', 'Dortmund', 'Essen',
    'Leipzig', 'Bremen', 'Dresden', 'Hannover', 'Nürnberg', 'Duisburg', 'Bonn', 'Aachen', 'Münster'],
  Бельгия: ['Brussel', 'Antwerpen', 'Gent', 'Charleroi', 'Liège', 'Brugge', 'Namur', 'Leuven', 'Mechelen', 'Aalst',
    'Hasselt', 'Kortrijk'],
};

export const asCountry = (v?: string | null): Country => (COUNTRIES as readonly string[]).includes(v || '') ? (v as Country) : DEFAULT_COUNTRY;
