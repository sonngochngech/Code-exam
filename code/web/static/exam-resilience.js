// BL-09: browser-only persistence scoped to one student and exam session.
export function createExamResilience(student, sessionId, storage = localStorage) {
  const answerKey = `exam:${student}:${sessionId}:answers`;
  const queueKey = `exam:${student}:${sessionId}:queue`;

  function read(key, fallback) {
    try { return JSON.parse(storage.getItem(key) || "null") ?? fallback; }
    catch (_) { storage.removeItem(key); return fallback; }
  }

  return {
    loadAnswers() { return read(answerKey, {}); },
    saveAnswers(answers) { storage.setItem(answerKey, JSON.stringify(answers)); },
    clearAnswers() { storage.removeItem(answerKey); },
    enqueue(kind, payload) {
      const queue = read(queueKey, []);
      queue.push({ kind, payload });
      storage.setItem(queueKey, JSON.stringify(queue));
    },
    async retry(send, onSuccess = () => {}) {
      const queue = read(queueKey, []), remaining = [];
      for (const item of queue) {
        try {
          const result = await send(item.kind, item.payload);
          onSuccess(item.kind, result);
        } catch (_) { remaining.push(item); }
      }
      storage.setItem(queueKey, JSON.stringify(remaining));
      return remaining.length;
    },
  };
}
