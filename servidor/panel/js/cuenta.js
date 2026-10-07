const Cuenta = {
    abrirModal() {
        document.getElementById('cuenta-pass-actual').value = '';
        document.getElementById('cuenta-pass-nueva').value = '';
        document.getElementById('cuenta-pass-confirmar').value = '';
        document.getElementById('modal-cuenta-error').textContent = '';
        document.getElementById('modal-cuenta-ok').classList.add('hidden');
        document.getElementById('modal-cuenta').classList.remove('hidden');
    },

    cerrarModal() {
        document.getElementById('modal-cuenta').classList.add('hidden');
    },

    async guardar() {
        const actual     = document.getElementById('cuenta-pass-actual').value;
        const nueva      = document.getElementById('cuenta-pass-nueva').value;
        const confirmar  = document.getElementById('cuenta-pass-confirmar').value;
        const errEl      = document.getElementById('modal-cuenta-error');
        const okEl       = document.getElementById('modal-cuenta-ok');
        errEl.textContent = '';
        okEl.classList.add('hidden');

        if (!actual || !nueva) { errEl.textContent = 'Completa ambos campos.'; return; }
        if (nueva.length < 12) { errEl.textContent = 'La nueva contraseña debe tener al menos 12 caracteres.'; return; }
        if (nueva.length > 128) { errEl.textContent = 'La nueva contraseña no puede superar los 128 caracteres.'; return; }
        if (nueva !== confirmar) { errEl.textContent = 'La confirmación no coincide con la contraseña nueva.'; return; }

        try {
            // Cambiar la contraseña invalida la cookie de sesión anterior (ver PUT
            // /auth/password en el servidor); el propio endpoint reescribe las cookies
            // (access_token/csrf_token) con una sesión nueva, así que acá no hace falta
            // guardar nada a mano — de lo contrario la siguiente petición del panel
            // devolvería 401 y forzaría un logout inesperado justo después de guardar.
            await API.cambiarPassword(actual, nueva);
            okEl.classList.remove('hidden');
            document.getElementById('cuenta-pass-actual').value = '';
            document.getElementById('cuenta-pass-nueva').value = '';
            document.getElementById('cuenta-pass-confirmar').value = '';
        } catch (e) {
            errEl.textContent = e.message || 'No se pudo cambiar la contraseña.';
        }
    },

    init() {
        document.getElementById('btn-cambiar-pass')?.addEventListener('click', () => this.abrirModal());
        document.getElementById('btn-cuenta-guardar')?.addEventListener('click', () => this.guardar());
        document.getElementById('btn-cuenta-cancelar')?.addEventListener('click', () => this.cerrarModal());
        document.getElementById('modal-cuenta')?.addEventListener('click', e => {
            if (e.target.id === 'modal-cuenta') this.cerrarModal();
        });
    }
};
