const API = "http://localhost:8000";

// token helpers
function getToken() { return localStorage.getItem("lazy_token"); }
function setToken(t) { if (t) localStorage.setItem("lazy_token", t); }
function clearToken() { localStorage.removeItem("lazy_token"); }

// fetch with Bearer, plus JSON default header
function authFetch(url, opts = {}) {
    const headers = { "content-type": "application/json", ...(opts.headers || {}) };
    const t = getToken();
    if (t) headers.authorization = `Bearer ${t}`;
    return fetch(url, { ...opts, headers });
}

// Get current user or null on any failure
async function getMe() {
    try {
        const res = await authFetch(`${API}/whoami`);
        if (!res.ok) return null;
        return await res.json();
    } catch {
        return null;
    }
}
