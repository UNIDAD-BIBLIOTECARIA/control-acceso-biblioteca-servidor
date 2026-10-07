const App = {
    currentTab: 'sesiones',
    refreshInterval: null,

    async init() {
        document.getElementById('btn-login').addEventListener('click', () => this.login());
        document.getElementById('btn-logout').addEventListener('click', () => this.logout());
        document.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !document.getElementById('login-screen').classList.contains('hidden'))
                this.login();
        });
        document.querySelectorAll('.tab').forEach(btn =>
            btn.addEventListener('click', () => this.cambiarTab(btn.dataset.tab))
        );
        Cuenta.init();

        if (await API.checkSession()) {
            await this.mostrarPanel();
        } else {
            document.getElementById('login-screen').classList.remove('hidden');
        }
    },

    async login() {
        const user = document.getElementById('username').value;
        const pass = document.getElementById('password').value;
        const err  = document.getElementById('login-error');
        err.textContent = '';
        try {
            await API.login(user, pass);
            await this.mostrarPanel();
        } catch (e) {
            err.textContent = e.message;
        }
    },

    logout() {
        // Varias peticiones en vuelo pueden recibir 401 a la vez y llamar acá
        // cada una: solo la primera cierra la sesión.
        if (document.getElementById('panel-screen').classList.contains('hidden')) return;
        API.logout();
        this._detenerRefresco();
        document.getElementById('panel-screen').classList.add('hidden');
        document.getElementById('login-screen').classList.remove('hidden');
        document.getElementById('tab-container').innerHTML = '';
    },

    async mostrarPanel() {
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('panel-screen').classList.remove('hidden');
        await this.cambiarTab('sesiones');
        clearInterval(this.refreshInterval);  // por si ya había uno de un login anterior
        this.refreshInterval = setInterval(() => {
            if (this.currentTab === 'sesiones') Sesiones.cargar();
            if (this.currentTab === 'pcs')      PCs.cargar();
        }, 30000);
    },

    _detenerRefresco() {
        clearInterval(this.refreshInterval);
        this.refreshInterval = null;
        Sesiones.detener();
    },

    async cambiarTab(tab) {
        if (this.currentTab === 'sesiones' && tab !== 'sesiones') Sesiones.detener();
        this.currentTab = tab;
        document.querySelectorAll('.tab').forEach(b => {
            const isActive = b.dataset.tab === tab;
            b.classList.toggle('active', isActive);
            b.setAttribute('aria-selected', String(isActive));
        });
        try {
            const res = await fetch(`/panel/views/${tab}.html`, { cache: 'no-store' });
            document.getElementById('tab-container').innerHTML = await res.text();
        } catch (e) {
            console.error('No se pudo cargar la vista:', tab, e);
            return;
        }
        if (tab === 'sesiones')     Sesiones.init();
        if (tab === 'pcs')          PCs.init();
        if (tab === 'estudiantes')  Estudiantes.init();
        if (tab === 'estadisticas') Estadisticas.init();
    }
};

const HTML_ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, c => HTML_ESCAPE_MAP[c]);
}

function fmtHora(iso) {
    if (!iso) return '—';
    const d = new Date(iso.replace(' ', 'T') + (iso.includes('T') ? '' : 'Z'));
    return d.toLocaleTimeString('es-GT', { hour: '2-digit', minute: '2-digit' });
}

function actualizarSelect(id, opciones, placeholder) {
    const sel = document.getElementById(id);
    if (!sel) return;
    const actual = sel.value;
    sel.innerHTML = `<option value="">${placeholder}</option>`;
    opciones.forEach(o => {
        // Cada opción puede ser un string (valor = etiqueta) o un par [valor, etiqueta].
        const [valor, etiqueta] = Array.isArray(o) ? o : [o, o];
        const opt = document.createElement('option');
        opt.value = valor; opt.textContent = etiqueta;
        if (valor === actual) opt.selected = true;
        sel.appendChild(opt);
    });
}

document.addEventListener('DOMContentLoaded', () => App.init());
