const Sesiones = {
    datos: [],
    _ticker: null,

    async cargar() {
        const fecha    = document.getElementById('filter-fecha')?.value   || '';
        const carrera  = document.getElementById('filter-carrera')?.value || '';
        const pc       = document.getElementById('filter-pc')?.value      || '';

        const params = new URLSearchParams();
        if (fecha)   params.set('fecha',   fecha);
        if (carrera) params.set('carrera', carrera);
        if (pc)      params.set('pc_id',   pc);

        try {
            const [sesiones, resumen] = await Promise.all([
                API.fetch(`/reportes/sesiones?${params}`),
                API.fetch(`/reportes/resumen-dia?fecha=${fecha}`),
            ]);

            this.datos = sesiones;
            this._renderResumen(resumen);
            this._actualizarFiltros(sesiones);
            this.filtrarLocal();
        } catch (e) { console.error(e); }
    },

    filtrarLocal() {
        const q       = document.getElementById('filter-carnet')?.value.toLowerCase() || '';
        const facultad = document.getElementById('filter-facultad')?.value || '';
        const filtered = this.datos.filter(s =>
            (!q       || (s.carnet||'').toLowerCase().includes(q) || (s.nombre||'').toLowerCase().includes(q)) &&
            (!facultad || s.facultad === facultad)
        );
        this._renderTabla(filtered);
    },

    exportarCSV() {
        const fecha = document.getElementById('filter-fecha')?.value || 'hoy';
        const headers = ['Carnet','Nombre','Carrera','Facultad','PC','Hora inicio','Hora fin','Minutos'];
        const rows = this.datos.map(s => [
            s.carnet||'Invitado', s.nombre||'', s.carrera||'', s.facultad||'',
            s.pc_nombre||s.pc_id||'', s.hora_inicio, s.hora_fin||'', s.minutos??''
        ]);
        const csv = [headers, ...rows].map(r => r.map(c => this._celdaCSV(c)).join(',')).join('\r\n');
        const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `sesiones_${fecha}.csv`;
        a.click();
    },

    // Campos como el nombre los escribe el propio estudiante en el kiosko, así que no son
    // de fiar: se duplican las comillas para no romper la fila y, si el texto empieza por
    // un carácter que Excel/LibreOffice interpretan como fórmula (= + - @, tab o CR), se
    // antepone un apóstrofo para que se muestre como texto y no se ejecute.
    _celdaCSV(valor) {
        let s = String(valor ?? '');
        if (typeof valor === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
        return `"${s.replace(/"/g, '""')}"`;
    },

    _elapsed(hora_inicio) {
        const start = new Date(hora_inicio.replace(' ', 'T'));
        const diff = Math.floor((Date.now() - start) / 60000);
        if (diff < 0) return null;
        const h = Math.floor(diff / 60), m = diff % 60;
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
    },

    _renderTabla(datos) {
        const tbody = document.getElementById('tabla-body');
        const noData = document.getElementById('no-data');
        if (!tbody) return;
        tbody.innerHTML = '';
        noData?.classList.toggle('hidden', datos.length > 0);
        datos.forEach(s => {
            const activa = !s.hora_fin;
            let dur;
            if (s.minutos != null) {
                dur = `${Math.floor(s.minutos/60)}h ${s.minutos%60}m`;
            } else if (activa) {
                dur = this._elapsed(s.hora_inicio) ?? '—';
            } else {
                dur = '—';
            }
            const tr = document.createElement('tr');
            const carnet = s.carnet ? escapeHtml(s.carnet) : '<span class="badge-invitado">Invitado</span>';
            const nombre = escapeHtml(s.nombre) || 'Sin nombre';
            tr.className = `compact-row${activa ? ' fila-activa' : ''}`;
            tr.innerHTML = `
                <td class="compact-summary" data-label="Sesión">
                    <button class="table-row-toggle" type="button" aria-expanded="false" aria-label="Ver detalles de ${nombre}">
                        <span class="compact-summary-kicker">${carnet}</span>
                        <span class="compact-summary-title">${nombre}</span>
                        <span class="table-toggle-indicator" aria-hidden="true">+</span>
                    </button>
                </td>
                <td class="compact-name-cell" data-label="Nombre">${nombre}</td>
                <td data-label="Carrera">${escapeHtml(s.carrera) || '—'}</td>
                <td data-label="PC">${escapeHtml(s.pc_nombre) || escapeHtml(s.pc_id) || '—'}</td>
                <td data-label="Hora inicio">${fmtHora(s.hora_inicio)}</td>
                <td data-label="Hora fin">${activa ? '<span class="badge-en-sesion">● En sesión</span>' : fmtHora(s.hora_fin)}</td>
                <td data-label="Duración" ${activa ? `class="dur-activa" data-hora-inicio="${escapeHtml(s.hora_inicio)}"` : ''}>${dur}</td>
            `;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll('.table-row-toggle').forEach(btn =>
            btn.addEventListener('click', () => this._toggleFila(btn))
        );
        this._iniciarTicker();
    },

    _toggleFila(btn) {
        if (!window.matchMedia('(max-width: 1024px)').matches) return;
        const fila = btn.closest('.compact-row');
        const abierta = fila.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', String(abierta));
    },

    _iniciarTicker() {
        clearInterval(this._ticker);
        this._ticker = setInterval(() => {
            document.querySelectorAll('td.dur-activa[data-hora-inicio]').forEach(td => {
                td.textContent = this._elapsed(td.dataset.horaInicio) ?? '—';
            });
        }, 60000);
    },

    // El refresco periódico de la tabla lo hace App (un solo intervalo para
    // todas las pestañas); acá solo queda el ticker que actualiza la duración
    // de las sesiones activas, y App lo detiene al salir de la pestaña.
    detener() {
        clearInterval(this._ticker);
        this._ticker = null;
    },

    _renderResumen(r) {
        const bar = document.getElementById('resumen-bar');
        if (!bar) return;
        bar.innerHTML = [
            { val: r.total_sesiones??0,   lbl: 'Sesiones hoy' },
            { val: r.estudiantes_unicos??0, lbl: 'Estudiantes únicos' },
            { val: r.pcs_usadas??0,        lbl: 'PCs usadas' },
            { val: r.minutos_promedio ? `${r.minutos_promedio} min` : '—', lbl: 'Promedio / sesión' },
        ].map(i => `<div class="resumen-item"><div class="val">${i.val}</div><div class="lbl">${i.lbl}</div></div>`).join('');
    },

    _actualizarFiltros(datos) {
        const uniq = (key) => [...new Set(datos.map(d => d[key]).filter(Boolean))].sort();
        actualizarSelect('filter-carrera', uniq('carrera'), 'Todas las carreras');
        actualizarSelect('filter-facultad', uniq('facultad'), 'Todas las facultades');

        const pcsPorId = new Map();
        datos.forEach(d => { if (d.pc_id) pcsPorId.set(d.pc_id, d.pc_nombre || d.pc_id); });
        const pcs = [...pcsPorId.entries()].sort((a, b) => a[1].localeCompare(b[1]));
        actualizarSelect('filter-pc', pcs, 'Todas las PCs');
    },

    init() {
        const hoy = new Date().toISOString().split('T')[0];
        const el = document.getElementById('filter-fecha');
        if (el && !el.value) el.value = hoy;

        document.getElementById('filter-fecha')?.addEventListener('change', () => this.cargar());
        document.getElementById('filter-carrera')?.addEventListener('change', () => this.cargar());
        document.getElementById('filter-facultad')?.addEventListener('change', () => this.filtrarLocal());
        document.getElementById('filter-pc')?.addEventListener('change', () => this.cargar());
        document.getElementById('filter-carnet')?.addEventListener('input', () => this.filtrarLocal());
        document.getElementById('btn-export')?.addEventListener('click', () => this.exportarCSV());

        this.cargar();
    }
};
