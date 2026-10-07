const API = {
    // La sesión ya no vive en sessionStorage ni se manda a mano con `Authorization: Bearer`
    // (ver AUDITORIA histórica, hallazgo M3): el servidor la guarda en una cookie
    // `access_token` HttpOnly (ilegible desde JS, así un XSS futuro en el panel no podría
    // robarla) que el navegador adjunta solo en cada request de este mismo origen.
    // `csrf_token` sí es legible: es el lado "doble-submit" de la protección CSRF que exige
    // el servidor en escrituras (ver `_verificar_csrf` en `routers/auth.py`).
    getCsrfToken() {
        const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : null;
    },

    async checkSession() {
        const res = await fetch('/auth/me', { credentials: 'same-origin' });
        return res.ok;
    },

    async fetch(url) {
        const res = await fetch(url, { credentials: 'same-origin' });
        if (res.status === 401) { App.logout(); throw new Error('Sesión expirada'); }
        return res.json();
    },

    async fetchRaw(url, { method = 'GET', body } = {}) {
        const headers = { 'Content-Type': 'application/json' };
        if (method !== 'GET') headers['X-CSRF-Token'] = this.getCsrfToken() || '';
        const opts = { method, headers, credentials: 'same-origin' };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        if (res.status === 401) { App.logout(); throw new Error('Sesión expirada'); }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            // Los errores de validación (422) traen `detail` como lista de
            // {msg, loc, ...}; los demás, como texto.
            const detalle = Array.isArray(err.detail)
                ? err.detail.map(d => String(d.msg || '').replace(/^Value error, /, '')).join(' ')
                : err.detail;
            throw new Error(detalle || `Error ${res.status}`);
        }
        return res.status === 204 ? null : res.json();
    },

    async cambiarPassword(passwordActual, passwordNueva) {
        return this.fetchRaw('/auth/password', {
            method: 'PUT',
            body: { password_actual: passwordActual, password_nueva: passwordNueva },
        });
    },

    async login(username, password) {
        const res = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Credenciales incorrectas');
        }
        return res.json();
    },

    async logout() {
        // No manda X-CSRF-Token: /auth/logout lo acepta sin él a propósito (ver docstring
        // en el servidor) para no bloquear el logout si por lo que sea la cookie csrf_token
        // ya no está disponible.
        await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
    }
};
