/**
 * Dataset loading: HTTP once, then IndexedDB.
 *
 * The full dataset is ~9 MB of JSON (~1.3 MB over the wire, gzipped by GitHub
 * Pages). Small enough to hold entirely in memory, so IndexedDB is not here for
 * capacity — it is here so that a repeat visit costs nothing and so the app
 * keeps working offline. `manifest.json` is a few hundred bytes and carries the
 * build's `scraped_at`, which is what lets us answer "is my copy current?"
 * without downloading the dataset to find out.
 */

const DB_NAME = 'mineduc-curriculum';
const DB_VERSION = 1;
const STORE = 'datasets';
const KEY = 'full';

const DATA_URL = './data/mineduc_curriculum_full.json';
const MANIFEST_URL = './data/manifest.json';

function openDb() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) {
      reject(new Error('IndexedDB unavailable'));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function tx(db, mode, fn) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    const request = fn(transaction.objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readCache() {
  try {
    const db = await openDb();
    const cached = await tx(db, 'readonly', (store) => store.get(KEY));
    db.close();
    return cached ?? null;
  } catch {
    return null; // private mode, blocked storage, quota — never fatal
  }
}

async function writeCache(entry) {
  try {
    const db = await openDb();
    await tx(db, 'readwrite', (store) => store.put(entry, KEY));
    db.close();
    return true;
  } catch {
    return false;
  }
}

export async function clearCache() {
  try {
    const db = await openDb();
    await tx(db, 'readwrite', (store) => store.delete(KEY));
    db.close();
  } catch { /* nothing to clear */ }
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} — ${url}`);
  return response.json();
}

/**
 * Resolve the dataset, preferring a current cached copy.
 *
 * `onProgress(stage)` is called with 'manifest' | 'cache' | 'download' | 'ready'
 * so the caller can say something honest while a first visit downloads.
 */
export async function loadDataset(onProgress = () => {}) {
  onProgress('manifest');

  let manifest = null;
  try {
    manifest = await fetchJson(MANIFEST_URL);
  } catch {
    manifest = null; // offline, or served without the manifest
  }

  const cached = await readCache();
  if (cached?.data && (!manifest || cached.scraped_at === manifest.scraped_at)) {
    onProgress('cache');
    return { data: cached.data, source: 'cache', manifest: manifest ?? cached.manifest };
  }

  if (!navigator.onLine && cached?.data) {
    // Offline with a stale copy still beats no copy at all.
    onProgress('cache');
    return { data: cached.data, source: 'cache-stale', manifest: cached.manifest };
  }

  onProgress('download');
  const data = await fetchJson(DATA_URL);
  const scraped_at = data?.metadata?.scraped_at ?? null;
  await writeCache({ scraped_at, manifest, data });
  onProgress('ready');
  return { data, source: 'network', manifest };
}
