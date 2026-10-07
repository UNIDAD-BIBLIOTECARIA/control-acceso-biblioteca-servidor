const Estudiantes = {
    datos: [],
    _editCarnet: null,

    async cargar() {
        try {
            this.datos = await API.fetch('/estudiantes');
            this.filtrar();
        } catch (e) { console.error(e); }
    },

    filtrar() {
        const q = document.getElementById('filter-est')?.value.toLowerCase() || '';
        const filtrados = this.datos.filter(e =>
            e.carnet.toLowerCase().includes(q) ||
            (e.nombre||'').toLowerCase().includes(q) ||
            (e.carrera||'').toLowerCase().includes(q)
        );
        this._render(filtrados);
    },

    _render(datos) {
        const tbody = document.getElementById('tabla-est-body');
        const noEl  = document.getElementById('no-est');
        if (!tbody) return;
        tbody.innerHTML = '';
        noEl?.classList.toggle('hidden', datos.length > 0);
        datos.forEach((e, index) => {
            const tr = document.createElement('tr');
            const carnet = escapeHtml(e.carnet);
            const nombre = escapeHtml(e.nombre) || 'Sin nombre';
            tr.className = 'student-row';
            tr.innerHTML = `
                <td class="student-summary" data-label="Estudiante">
                    <button class="student-row-toggle" type="button" aria-expanded="false" aria-label="Ver detalles de ${nombre}">
                        <span class="student-summary-carnet">${carnet}</span>
                        <span class="student-summary-name">${nombre}</span>
                        <span class="student-toggle-indicator" aria-hidden="true">+</span>
                    </button>
                </td>
                <td class="student-name-cell" data-label="Nombre">${nombre}</td>
                <td data-label="Carrera">${escapeHtml(e.carrera) || '—'}</td>
                <td data-label="Facultad">${escapeHtml(e.facultad) || '—'}</td>
                <td data-label="Sexo">${escapeHtml(e.sexo) || '—'}</td>
                <td data-label="Registro">${escapeHtml(e.fecha_registro) || '—'}</td>
                <td class="student-action" data-label="Acciones"><button class="btn-edit-est" data-carnet="${carnet}">Editar</button></td>
            `;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll('.student-row-toggle').forEach(btn =>
            btn.addEventListener('click', () => this._toggleFila(btn))
        );
        tbody.querySelectorAll('.btn-edit-est').forEach(btn =>
            btn.addEventListener('click', () => this._abrirEditar(btn.dataset.carnet))
        );
    },

    _toggleFila(btn) {
        if (!window.matchMedia('(max-width: 1024px)').matches) return;
        const fila = btn.closest('.student-row');
        const abierta = fila.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', String(abierta));
    },

    // Facultad -> carreras válidas (GET /estudiantes/catalogo). El servidor
    // rechaza combinaciones fuera del catálogo; acá solo se ofrecen como
    // sugerencias en los campos del formulario.
    _catalogo: {},

    async _cargarCatalogo() {
        try {
            this._catalogo = await API.fetch('/estudiantes/catalogo');
        } catch (e) {
            this._catalogo = {};
        }
        this._llenarDatalist('dl-est-facultades', Object.keys(this._catalogo));
    },

    _llenarDatalist(id, valores) {
        const dl = document.getElementById(id);
        if (!dl) return;
        dl.replaceChildren(...valores.map(v => {
            const opt = document.createElement('option');
            opt.value = v;
            return opt;
        }));
    },

    _actualizarCarreras() {
        const facultad = document.getElementById('est-facultad').value.trim();
        this._llenarDatalist('dl-est-carreras', this._catalogo[facultad] || []);
    },

    _abrirModal(titulo, datos = {}) {
        document.getElementById('modal-est-titulo').textContent = titulo;
        document.getElementById('est-carnet').value       = datos.carnet      || '';
        document.getElementById('est-carnet').disabled    = !!datos.carnet;
        document.getElementById('est-nombre').value       = datos.nombre      || '';
        document.getElementById('est-carrera').value      = datos.carrera     || '';
        document.getElementById('est-facultad').value     = datos.facultad    || '';
        this._actualizarCarreras();
        document.getElementById('est-fecha-nac').value    = datos.fecha_nacimiento || '';
        document.getElementById('est-sexo').value         = datos.sexo        || '';
        document.getElementById('modal-est-error').textContent = '';
        document.getElementById('modal-est').classList.remove('hidden');
    },

    _cerrarModal() {
        document.getElementById('modal-est').classList.add('hidden');
        this._editCarnet = null;
    },

    _abrirNuevo() {
        this._editCarnet = null;
        this._abrirModal('Nuevo estudiante');
    },

    _abrirEditar(carnet) {
        const est = this.datos.find(e => e.carnet === carnet);
        if (!est) return;
        this._editCarnet = carnet;
        this._abrirModal('Editar estudiante', est);
    },

    async _guardar() {
        const carnet      = document.getElementById('est-carnet').value.trim();
        const nombre      = document.getElementById('est-nombre').value.trim();
        const carrera     = document.getElementById('est-carrera').value.trim();
        const facultad    = document.getElementById('est-facultad').value.trim();
        const fecha_nac   = document.getElementById('est-fecha-nac').value;
        const sexo        = document.getElementById('est-sexo').value;
        const errEl       = document.getElementById('modal-est-error');

        if (!carnet || !nombre) { errEl.textContent = 'Carnet y nombre son requeridos.'; return; }

        const body = { carnet, nombre, carrera: carrera||null, facultad: facultad||null,
                       fecha_nacimiento: fecha_nac||null, sexo: sexo||null };
        try {
            if (this._editCarnet) {
                await API.fetchRaw(`/estudiantes/${this._editCarnet}`, { method: 'PUT', body });
            } else {
                await API.fetchRaw('/estudiantes', { method: 'POST', body });
            }
            this._cerrarModal();
            await this.cargar();
        } catch (e) {
            errEl.textContent = e.message || 'Error al guardar.';
        }
    },

    init() {
        document.getElementById('filter-est')?.addEventListener('input', () => this.filtrar());
        document.getElementById('btn-nuevo-est')?.addEventListener('click', () => this._abrirNuevo());
        document.getElementById('est-facultad')?.addEventListener('input', () => this._actualizarCarreras());
        document.getElementById('btn-est-guardar')?.addEventListener('click', () => this._guardar());
        document.getElementById('btn-est-cancelar')?.addEventListener('click', () => this._cerrarModal());
        document.getElementById('modal-est')?.addEventListener('click', e => {
            if (e.target.id === 'modal-est') this._cerrarModal();
        });
        this._cargarCatalogo();
        this.cargar();
    }
};
