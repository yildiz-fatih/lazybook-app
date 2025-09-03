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

// Pretty-print a single post
function renderPost(post) {
    const postContainer = document.createElement('div');

    const postHeader = document.createElement('div');

    // Create username link
    const usernameLink = document.createElement('a');
    usernameLink.href = `./user.html?id=${post.user_id}`;
    usernameLink.textContent = post.username;
    postHeader.appendChild(usernameLink);

    // Create timestamp
    const timestampElement = document.createElement('small');
    const formattedDate = new Date(post.created_at).toLocaleString();
    timestampElement.textContent = ` ${formattedDate}`;
    postHeader.appendChild(timestampElement);

    // Create post content
    const postContent = document.createElement('p');
    postContent.style.wordBreak = 'break-word';
    postContent.textContent = post.contents || '';
    postHeader.appendChild(postContent);

    // Assemble
    postContainer.appendChild(postHeader);

    // Add horizontal separator
    const separator = document.createElement('hr');
    postContainer.appendChild(separator);

    return postContainer;
}