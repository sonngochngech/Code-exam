// BL-09: browser-only persistence scoped to one student and exam session.
//
// M7: every storage call is guarded. If the browser refuses to store (quota full,
// private mode, blocked site data) the data stays in memory for this page, and
// `onStorageError` is called once so the page can warn the student.

function openStorage() {
  try { return localStorage; } catch (_) { return null; }
}

// A rejection that will never succeed on retry (the server said no) must not sit in
// the queue forever. Network failures, server errors and "paused" (423) are retried.
function isPermanent(error) {
  const status = error && error.status;
  return status >= 400 && status < 500 && ![408, 423, 429].includes(status);
}

export function createExamResilience(student, sessionId, storage = openStorage()) {
  const answerKey = `exam:${student}:${sessionId}:answers`;
  const queueKey = `exam:${student}:${sessionId}:queue`;
  const memory = {};
  let warned = false;

  const api = {
    onStorageError: () => {},

    read(key, fallback) {
      try {
        const text = storage ? storage.getItem(key) : null;
        if (text !== null && text !== undefined) return JSON.parse(text) ?? fallback;
      } catch (_) {
        try { storage.removeItem(key); } catch (__) { /* nothing more to do */ }
      }
      return key in memory ? memory[key] : fallback;
    },

    write(key, value) {
      memory[key] = value;
      try {
        if (!storage) throw new Error("no storage");
        storage.setItem(key, JSON.stringify(value));
        return true;
      } catch (_) {
        if (!warned) { warned = true; api.onStorageError(); }
        return false;
      }
    },

    remove(key) {
      delete memory[key];
      try { if (storage) storage.removeItem(key); } catch (_) { /* ignore */ }
    },

    loadAnswers() { return api.read(answerKey, {}); },
    saveAnswers(answers) { return api.write(answerKey, answers); },
    clearAnswers() { api.remove(answerKey); },

    enqueue(kind, payload) {
      const queue = api.read(queueKey, []);
      queue.push({ kind, payload });
      return api.write(queueKey, queue);
    },

    pending(kind) {
      return api.read(queueKey, []).filter(item => !kind || item.kind === kind).length;
    },

    async retry(send, onSuccess = () => {}, onDrop = () => {}) {
      const queue = api.read(queueKey, []), remaining = [];
      for (const item of queue) {
        try {
          const result = await send(item.kind, item.payload);
          onSuccess(item.kind, result);
        } catch (error) {
          if (isPermanent(error)) onDrop(item.kind, error);
          else remaining.push(item);
        }
      }
      api.write(queueKey, remaining);
      return remaining.length;
    },
  };
  return api;
}
