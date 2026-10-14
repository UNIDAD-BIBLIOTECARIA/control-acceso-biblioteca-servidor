const Estadisticas = {
    charts: {},

    async init() {
        await this._loadChartJs();

        const hoy = fechaLocalISO();
        const hace7 = fechaLocalISO(new Date(Date.now() - 6 * 86400000));

        document.getElementById('est-desde').value = hace7;
        document.getElementById('est-hasta').value = hoy;

        document.querySelectorAll('.est-quick').forEach(btn =>
            btn.addEventListener('click', () => {
                document.querySelectorAll('.est-quick').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const dias = parseInt(btn.dataset.dias);
                const desde = fechaLocalISO(new Date(Date.now() - (dias - 1) * 86400000));
                document.getElementById('est-desde').value = desde;
                document.getElementById('est-hasta').value = hoy;
                this.cargar();
            })
        );

        document.getElementById('est-btn-aplicar').addEventListener('click', () => {
            document.querySelectorAll('.est-quick').forEach(b => b.classList.remove('active'));
            this.cargar();
        });

        this.cargar();
    },

    async cargar() {
        const desde = document.getElementById('est-desde').value;
        const hasta = document.getElementById('est-hasta').value;

        try {
            const data = await API.fetch(`/reportes/estadisticas?desde=${desde}&hasta=${hasta}`);
            this._renderCards(data.totales, desde, hasta);
            this._renderPorDia(data.por_dia);
            this._renderPorHora(data.por_hora);
            this._renderPorSexo(data.por_sexo);
            this._renderHBar('chart-por-carrera', data.por_carrera, 'carrera', 'sesiones');
            this._renderHBar('chart-por-facultad', data.por_facultad, 'facultad', 'sesiones');
            this._renderHBar('chart-por-pc', data.por_pc, 'pc_nombre', 'sesiones');
        } catch (e) {
            console.error('Error cargando estadísticas:', e);
        }
    },

    _renderCards(t, desde, hasta) {
        const totalHoras = t.total_minutos ? Math.round(t.total_minutos / 60) : 0;
        const promMin = t.minutos_promedio ?? 0;
        const promFmt = promMin >= 60
            ? `${Math.floor(promMin / 60)}h ${promMin % 60}m`
            : `${promMin}m`;

        const cards = [
            { val: t.total_sesiones ?? 0,    lbl: 'Sesiones totales',    icon: '📋' },
            { val: t.total_estudiantes ?? 0,  lbl: 'Estudiantes únicos',  icon: '🎓' },
            { val: `${totalHoras}h`,          lbl: 'Horas de uso total',  icon: '⏱' },
            { val: promFmt,                   lbl: 'Promedio / sesión',   icon: '📊' },
        ];
        document.getElementById('est-resumen-cards').innerHTML = cards
            .map(c => `<div class="est-card"><div class="est-card-icon">${c.icon}</div><div class="est-card-val">${c.val}</div><div class="est-card-lbl">${c.lbl}</div></div>`)
            .join('');
    },

    _renderPorDia(datos) {
        const labels = datos.map(d => {
            const [y, m, day] = d.fecha.split('-');
            return `${day}/${m}`;
        });
        const values = datos.map(d => d.sesiones);
        this._destroyChart('chart-por-dia');
        this.charts['chart-por-dia'] = new Chart(
            document.getElementById('chart-por-dia').getContext('2d'),
            {
                type: 'line',
                data: {
                    labels,
                    datasets: [{
                        label: 'Sesiones',
                        data: values,
                        borderColor: '#696969',
                        backgroundColor: 'rgba(105,105,105,0.08)',
                        fill: true,
                        tension: 0.3,
                        pointBackgroundColor: '#8B0E13',
                        pointRadius: datos.length <= 31 ? 4 : 2,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { ticks: { maxTicksLimit: 15 } }
                    }
                }
            }
        );
    },

    _renderPorHora(datos) {
        const allHours = Array.from({ length: 24 }, (_, i) => i);
        const map = Object.fromEntries(datos.map(d => [d.hora, d.sesiones]));
        const values = allHours.map(h => map[h] ?? 0);
        const labels = allHours.map(h => `${String(h).padStart(2, '0')}:00`);

        this._destroyChart('chart-por-hora');
        this.charts['chart-por-hora'] = new Chart(
            document.getElementById('chart-por-hora').getContext('2d'),
            {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Sesiones',
                        data: values,
                        backgroundColor: values.map(v => {
                            const max = Math.max(...values);
                            const alpha = max > 0 ? 0.3 + (v / max) * 0.7 : 0.3;
                            return `rgba(139,14,19,${alpha.toFixed(2)})`;
                        }),
                        borderRadius: 3,
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { ticks: { maxRotation: 90, minRotation: 45 } }
                    }
                }
            }
        );
    },

    _renderPorSexo(datos) {
        const colorMap = {
            'M': '#1A171B', 'F': '#8B0E13',
            'LGBTIQ+': '#D97706', 'N/D': '#696969',
            'No especificado': '#ABABAB',
        };
        const labels = datos.map(d => d.sexo);
        const values = datos.map(d => d.sesiones);
        const colors = labels.map(l => colorMap[l] || '#696969');

        this._destroyChart('chart-por-sexo');
        this.charts['chart-por-sexo'] = new Chart(
            document.getElementById('chart-por-sexo').getContext('2d'),
            {
                type: 'doughnut',
                data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2 }] },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom' },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                    const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                                    return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`;
                                }
                            }
                        }
                    }
                }
            }
        );
    },

    _renderHBar(canvasId, datos, labelKey, valueKey) {
        const labels = datos.map(d => d[labelKey]);
        const values = datos.map(d => d[valueKey]);

        this._destroyChart(canvasId);
        this.charts[canvasId] = new Chart(
            document.getElementById(canvasId).getContext('2d'),
            {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Sesiones',
                        data: values,
                        backgroundColor: 'rgba(139,14,19,0.75)',
                        borderRadius: 3,
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { beginAtZero: true, ticks: { precision: 0 } },
                        y: { ticks: { font: { size: 11 } } }
                    }
                }
            }
        );
    },

    _destroyChart(id) {
        if (this.charts[id]) {
            this.charts[id].destroy();
            delete this.charts[id];
        }
    },

    _loadChartJs() {
        if (window.Chart) return Promise.resolve();
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js';
            // SRI: si jsdelivr sirve un archivo distinto al esperado
            // (compromiso del CDN, downgrade, typo de versión), el navegador
            // rechaza el script en vez de ejecutarlo.
            s.integrity = 'sha384-NrKB+u6Ts6AtkIhwPixiKTzgSKNblyhlk0Sohlgar9UHUBzai/sgnNNWWd291xqt';
            s.crossOrigin = 'anonymous';
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    },
};
