/* Offline store: books pages + session hint on device (IndexedDB) */
(function (global) {
  const DB_NAME = 'churchgate_offline_v1';
  const DB_VER = 1;

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('books')) {
          db.createObjectStore('books', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('meta')) {
          db.createObjectStore('meta', { keyPath: 'key' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function putBook(book) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('books', 'readwrite');
      tx.objectStore('books').put({
        id: String(book.id),
        title: book.title || 'Book',
        pages: book.pages || [],
        pageIndex: book.pageIndex || 0,
        updatedAt: Date.now(),
      });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function getBook(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('books', 'readonly');
      const req = tx.objectStore('books').get(String(id));
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async function listBooks() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('books', 'readonly');
      const req = tx.objectStore('books').getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function setMeta(key, value) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('meta', 'readwrite');
      tx.objectStore('meta').put({ key, value, updatedAt: Date.now() });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function getMeta(key) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('meta', 'readonly');
      const req = tx.objectStore('meta').get(key);
      req.onsuccess = () => resolve(req.result ? req.result.value : null);
      req.onerror = () => reject(req.error);
    });
  }

  function isOnline() {
    return navigator.onLine !== false;
  }

  global.CGOffline = { putBook, getBook, listBooks, setMeta, getMeta, isOnline };
})(window);
