// Tell search engines that use IndexNow (Bing, which feeds ChatGPT search and Copilot,
// plus Yandex, Seznam and others) that the site's pages changed. Run after a deploy
// is live:  node scripts/indexnow.mjs
// The key is not a secret: IndexNow checks it against public/<key>.txt on the site.
const KEY = '702cc373f553fe80a11ee210b94fd043';
const HOST = 'ansibangla.cc';
const urls = ['https://ansibangla.cc/', 'https://ansibangla.cc/how-it-works/'];

const res = await fetch('https://api.indexnow.org/indexnow', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: JSON.stringify({ host: HOST, key: KEY, keyLocation: `https://${HOST}/${KEY}.txt`, urlList: urls }),
});
// 200 = received, 202 = received (key check pending), 403 = key file not found yet
console.log(res.status, res.statusText || '', '-', urls.length, 'URLs');
