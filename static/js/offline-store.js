/* Offline store: books + background music blobs on device */
(function (global) {
  const DB_NAME = 'churchgate_offline_v2';
  const DB_VER = 2;

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VER);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('books')) db.createObjectStore('books', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: 'key' });
        if (!db.objectStoreNames.contains('bgm')) db.createObjectStore('bgm', { keyPath: 'id' });
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
      const req = db.transaction('books', 'readonly').objectStore('books').get(String(id));
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }
  async function listBooks() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const req = db.transaction('books', 'readonly').objectStore('books').getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }
  async function putBgm(item) {
    // item: { id, title, blob }
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('bgm', 'readwrite');
      tx.objectStore('bgm').put({
        id: String(item.id),
        title: item.title || 'Track',
        blob: item.blob,
        updatedAt: Date.now(),
      });
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }
  async function listBgm() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const req = db.transaction('bgm', 'readonly').objectStore('bgm').getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }
  async function getBgm(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const req = db.transaction('bgm', 'readonly').objectStore('bgm').get(String(id));
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }
  async function deleteBgm(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('bgm', 'readwrite');
      tx.objectStore('bgm').delete(String(id));
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
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
      const req = db.transaction('meta', 'readonly').objectStore('meta').get(key);
      req.onsuccess = () => resolve(req.result ? req.result.value : null);
      req.onerror = () => reject(req.error);
    });
  }
  function isOnline() { return navigator.onLine !== false; }

  global.CGOffline = {
    putBook, getBook, listBooks, putBgm, listBgm, getBgm, deleteBgm, setMeta, getMeta, isOnline,
  };
})(window);
