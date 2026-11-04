// Двенадцать провинций Нидерландов. Названия латиницей, как в бренд-буке.
// Описание и координаты центра — с сайта (wordpress/src/data/prov2.json), города — по utils/geo.py сервера и дополнены.
// Порядок — с севера на юг.

export type ProvinceId = 'gr' | 'fr' | 'dr' | 'ov' | 'fl' | 'ge' | 'ut' | 'nh' | 'zh' | 'ze' | 'nb' | 'li';

export type Province = { id: ProvinceId; name: string; capital: string; lat: number; lon: number; short: string; cities: string[] };

export const PROVINCES: Province[] = [
  {id: "gr", name: "Groningen", capital: "Groningen", lat: 53.25, lon: 6.75, short: "Север страны. Студенческий город, добыча газа, чистый воздух.", cities: ["Groningen", "Delfzijl", "Veendam", "Hoogezand", "Stadskanaal", "Winschoten", "Haren"]},
  {id: "fr", name: "Friesland", capital: "Leeuwarden", lat: 53.1, lon: 5.8, short: "Свой язык, озёра, мельницы и марафон Elfstedentocht.", cities: ["Leeuwarden", "Sneek", "Heerenveen", "Drachten", "Harlingen", "Franeker", "Dokkum", "Bolsward", "Joure", "Terschelling", "Ameland", "Vlieland", "Schiermonnikoog"]},
  {id: "dr", name: "Drenthe", capital: "Assen", lat: 52.85, lon: 6.6, short: "Самая малонаселённая провинция. Доисторические мегалиты, природа.", cities: ["Assen", "Emmen", "Hoogeveen", "Meppel", "Coevorden", "Roden"]},
  {id: "ov", name: "Overijssel", capital: "Zwolle", lat: 52.43, lon: 6.45, short: "Исторические города Zwolle и Deventer. Красивые реки.", cities: ["Zwolle", "Enschede", "Deventer", "Hengelo", "Almelo", "Kampen", "Oldenzaal", "Giethoorn", "Steenwijk", "Hardenberg", "Rijssen"]},
  {id: "fl", name: "Flevoland", capital: "Lelystad", lat: 52.52, lon: 5.55, short: "Самая молодая провинция, созданная на осушенных землях в XX веке.", cities: ["Almere", "Lelystad", "Dronten", "Emmeloord", "Zeewolde", "Urk"]},
  {id: "ge", name: "Gelderland", capital: "Arnhem", lat: 52.05, lon: 5.95, short: "Крупнейшая провинция по площади. Нацпарки, реки Рейн и Waal.", cities: ["Arnhem", "Nijmegen", "Apeldoorn", "Ede", "Wijchen", "Doetinchem", "Harderwijk", "Zutphen", "Tiel", "Wageningen", "Barneveld", "Culemborg", "Winterswijk", "Zevenaar", "Nijkerk", "Elburg", "Otterlo", "Hoge Veluwe"]},
  {id: "ut", name: "Utrecht", capital: "Utrecht", lat: 52.08, lon: 5.2, short: "Историческое сердце Нидерландов. Один из старейших городов с собором Domkerk.", cities: ["Utrecht", "Amersfoort", "Nieuwegein", "Veenendaal", "Zeist", "Houten", "IJsselstein", "Woerden", "Soest", "Baarn", "Maarssen", "Doorn", "Bunnik"]},
  {id: "nh", name: "Noord-Holland", capital: "Haarlem", lat: 52.6, lon: 4.85, short: "Самая населённая провинция. Amsterdam, каналы, музеи мирового уровня.", cities: ["Amsterdam", "Haarlem", "Alkmaar", "Zaandam", "Zaanstad", "Hilversum", "Amstelveen", "Hoofddorp", "Haarlemmermeer", "Purmerend", "Hoorn", "Den Helder", "Heerhugowaard", "Velsen", "IJmuiden", "Zandvoort", "Bussum", "Huizen", "Edam", "Volendam", "Enkhuizen", "Texel", "Zaanse Schans", "Bloemendaal", "Diemen", "Weesp", "Naarden", "Muiden", "Schiphol"]},
  {id: "zh", name: "Zuid-Holland", capital: "Den Haag", lat: 52.0, lon: 4.5, short: "Rotterdam, крупнейший порт Европы, и Den Haag, политическая столица.", cities: ["Rotterdam", "Den Haag", "Leiden", "Delft", "Dordrecht", "Zoetermeer", "Schiedam", "Vlaardingen", "Gouda", "Alphen aan den Rijn", "Rijswijk", "Westland", "Capelle aan den IJssel", "Spijkenisse", "Katwijk", "Noordwijk", "Lisse", "Keukenhof", "Scheveningen", "Wassenaar", "Leidschendam", "Voorburg", "Kinderdijk", "Gorinchem", "Hellevoetsluis", "Maassluis", "Ridderkerk", "Barendrecht"]},
  {id: "ze", name: "Zeeland", capital: "Middelburg", lat: 51.5, lon: 3.85, short: "Острова и море. Устрицы, самый солнечный регион Нидерландов.", cities: ["Middelburg", "Vlissingen", "Goes", "Terneuzen", "Zierikzee", "Domburg", "Hulst", "Veere"]},
  {id: "nb", name: "Noord-Brabant", capital: "'s-Hertogenbosch", lat: 51.58, lon: 5.2, short: "Южная провинция. Карнавал, пивоварни, высокотехнологичный Eindhoven.", cities: ["Eindhoven", "Tilburg", "Breda", "Den Bosch", "'s-Hertogenbosch", "Helmond", "Oss", "Uden", "Veghel", "Roosendaal", "Bergen op Zoom", "Oosterhout", "Waalwijk", "Kaatsheuvel", "Efteling", "Veldhoven", "Best", "Boxtel", "Vught", "Heusden", "Etten-Leur", "Valkenswaard", "Geldrop", "Cuijk", "Boxmeer"]},
  {id: "li", name: "Limburg", capital: "Maastricht", lat: 51.2, lon: 5.9, short: "Единственная провинция с холмами. Граничит с Бельгией и Германией.", cities: ["Maastricht", "Venlo", "Heerlen", "Sittard", "Geleen", "Roermond", "Weert", "Kerkrade", "Valkenburg", "Venray", "Brunssum", "Landgraaf", "Vaals", "Thorn"]},
];

const BY_ID = Object.fromEntries(PROVINCES.map((p) => [p.id, p])) as Record<ProvinceId, Province>;
export const provinceById = (id: string | null | undefined): Province | null => (id && id in BY_ID ? BY_ID[id as ProvinceId] : null);

const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/^'s-/, '').replace(/[^a-z]/g, '');
const CITY: Record<string, ProvinceId> = {};
for (const p of PROVINCES) for (const c of p.cities) CITY[norm(c)] = p.id;
/** Провинция по названию города или места ('Valkenburg' → li). null — город неизвестен. */
export function provinceOfCity(city?: string | null): ProvinceId | null {
  if (!city) return null;
  const n = norm(city);
  if (CITY[n]) return CITY[n];
  const hit = Object.keys(CITY).find((k) => n.includes(k) || (n.length > 4 && k.includes(n)));
  return hit ? CITY[hit] : null;
}

/** Ближайшая провинция по координатам центра. Это подсказка для выбора, человек подтверждает её сам. */
export function nearestProvince(lat: number, lon: number): Province {
  const k = Math.cos((52 * Math.PI) / 180);
  let best = PROVINCES[0]; let bd = Infinity;
  for (const p of PROVINCES) { const d = (p.lat - lat) ** 2 + ((p.lon - lon) * k) ** 2; if (d < bd) { bd = d; best = p; } }
  return best;
}
