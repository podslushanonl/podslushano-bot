// Настройки Expo поверх app.json.
// Android-уведомления идут через Firebase Cloud Messaging: нужен файл google-services.json.
// Его не храним в репозитории — в EAS он задаётся как файловая переменная окружения GOOGLE_SERVICES_JSON
// (expo.dev → проект → Environment variables → тип «File»). Локально можно положить файл рядом с app.json.
const fs = require('fs');

module.exports = ({ config }) => {
  const file = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync('./google-services.json') ? './google-services.json' : undefined);
  return file ? { ...config, android: { ...config.android, googleServicesFile: file } } : config;
};
