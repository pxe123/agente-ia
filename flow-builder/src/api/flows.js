let cachedCsrfToken = null;

export async function getCsrfToken() {
  if (cachedCsrfToken) return cachedCsrfToken;
  const r = await fetch('/api/csrf-token', { credentials: 'include' });
  const data = await r.json().catch(() => ({}));
  const token = (data && data.csrf_token) ? String(data.csrf_token).trim() : '';
  cachedCsrfToken = token;
  return token;
}

export async function fetchFlowsList() {
  const response = await fetch('/api/flows', { credentials: 'include' });
  return response.json();
}

export async function fetchFlowJson({ chatbotId, channel }) {
  const ch = channel;
  const cid = chatbotId;
  const url = cid
    ? `/api/flow?chatbot_id=${encodeURIComponent(cid)}`
    : `/api/flow?channel=${encodeURIComponent(ch)}`;
  const response = await fetch(url, { credentials: 'include' });
  return response.json();
}

export async function saveFlowJson(payload) {
  const token = await getCsrfToken();
  const response = await fetch('/api/flow', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': token,
    },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  let json;
  try {
    json = await response.json();
  } catch {
    json = null;
  }
  return { response, json };
}

