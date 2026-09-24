/**
 * Основное приложение Alpine.js для управления оборотом картриджей
 * Поддержка: Авторизация (локальная/AD), Филиалы, Управление пользователями, WhatsApp и ручная выдача.
 */

function cartridgeApp() {
    return {
        // Авторизация и текущий пользователь
        authToken: localStorage.getItem('cartridge_token') || '',
        currentUser: null,
        isAuthChecking: true,
        authHeaders(extra = {}) {
            const h = { ...extra };
            if (this.authToken) {
                h['Authorization'] = `Bearer ${this.authToken}`;
            }
            return h;
        },
        loginForm: {
            username: '',
            password: '',
            auth_type: 'local' // 'local' | 'ad'
        },
        loginError: '',
        isLoggingIn: false,

        // Текущая навигация
        currentTab: 'acceptance', // 'acceptance' | 'batch' | 'return' | 'issue' | 'registry' | 'settings'
        settingsTab: 'branches',  // 'branches' | 'users' | 'ad' | 'whatsapp' | 'general'
        batchSubTab: 'create',    // 'create' | 'history'

        // Филиалы
        branches: [],
        activeBranchFilter: '', // '' = Все филиалы

        // Уведомления (Toasts)
        toasts: [],
        showToast(message, type = 'success') {
            const id = Date.now();
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 4500);
        },

        // Глобальные счетчики
        stats: {
            pending: 0,
            at_vendor: 0,
            ready: 0,
            in_use: 0,
            total: 0
        },

        // Настройки
        settings: {},

        // Инициализация
        async init() {
            // Глобальный перехватчик fetch для автоматической подстановки токена авторизации
            if (!window._cartridgeFetchIntercepted) {
                window._cartridgeFetchIntercepted = true;
                const originalFetch = window.fetch;
                window.fetch = async (...args) => {
                    let [resource, config] = args;
                    config = config || {};
                    config.headers = config.headers || {};
                    const token = localStorage.getItem('cartridge_token');
                    if (token) {
                        if (config.headers instanceof Headers) {
                            if (!config.headers.has('Authorization')) {
                                config.headers.set('Authorization', `Bearer ${token}`);
                            }
                        } else if (Array.isArray(config.headers)) {
                            const hasAuth = config.headers.some(([k]) => k.toLowerCase() === 'authorization');
                            if (!hasAuth) {
                                config.headers.push(['Authorization', `Bearer ${token}`]);
                            }
                        } else {
                            if (!config.headers['Authorization'] && !config.headers['authorization']) {
                                config.headers['Authorization'] = `Bearer ${token}`;
                            }
                        }
                    }
                    const response = await originalFetch(resource, config);
                    return response;
                };
            }

            if (this.authToken) {
                await this.fetchCurrentUser();
            } else {
                this.isAuthChecking = false;
            }

            if (this.currentUser) {
                this.applyRoleTabConstraints();
                await this.loadInitialData();
            }
        },

        applyRoleTabConstraints() {
            if (!this.currentUser) return;
            const r = this.currentUser.role;
            if (r === 'user') {
                this.currentTab = 'registry';
            } else if (r === 'operator') {
                if (this.currentTab === 'settings') {
                    this.currentTab = 'acceptance';
                }
            } else if (r === 'admin') {
                if (this.currentTab === 'settings') {
                    if (this.settingsTab !== 'branches' && (this.settingsTab !== 'whatsapp' || this.settings?.wa_mode !== 'individual')) {
                        this.settingsTab = 'branches';
                    }
                }
            }
        },

        async loadInitialData() {
            await this.loadBranches();
            if (this.currentUser?.role === 'user') {
                this.currentTab = 'registry';
                await this.loadRegistry();
                return;
            }

            await this.loadSettings();
            await this.refreshStats();
            this.loadPendingCartridges();
            this.initAcceptanceBranch();
            this.checkPersonalWaStatus();
            this.checkWaStatus();
        },

        // ==========================================
        // АВТОРИЗАЦИЯ
        // ==========================================
        async login() {
            if (!this.loginForm.username.trim() || !this.loginForm.password) {
                this.loginError = 'Введите логин и пароль.';
                return;
            }

            this.isLoggingIn = true;
            this.loginError = '';
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.loginForm)
                });

                if (res.ok) {
                    const data = await res.json();
                    this.authToken = data.access_token;
                    localStorage.setItem('cartridge_token', this.authToken);
                    this.currentUser = data.user;
                    this.loginForm.password = '';
                    this.applyRoleTabConstraints();
                    this.showToast(`Добро пожаловать, ${this.currentUser.full_name}!`, 'success');
                    await this.loadInitialData();
                } else {
                    const err = await res.json();
                    this.loginError = err.detail || 'Неверный логин или пароль.';
                }
            } catch (e) {
                this.loginError = 'Ошибка соединения с сервером.';
            } finally {
                this.isLoggingIn = false;
            }
        },

        async fetchCurrentUser() {
            this.isAuthChecking = true;
            try {
                const res = await fetch('/api/auth/me', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (res.ok) {
                    this.currentUser = await res.json();
                    this.applyRoleTabConstraints();
                } else {
                    this.logout(false);
                }
            } catch (e) {
                console.error(e);
            } finally {
                this.isAuthChecking = false;
            }
        },

        logout(notify = true) {
            this.authToken = '';
            this.currentUser = null;
            localStorage.removeItem('cartridge_token');
            if (notify) {
                this.showToast('Вы вышли из системы.', 'info');
            }
        },

        // ==========================================
        // ФИЛИАЛЫ
        // ==========================================
        async loadBranches() {
            try {
                const res = await fetch('/api/branches');
                if (res.ok) {
                    this.branches = await res.json();
                }
            } catch (e) {
                console.error('Error loading branches:', e);
            }
        },

        getBranchName(branchId) {
            if (!branchId) return 'Все филиалы';
            const b = this.branches.find(x => x.id === branchId);
            return b ? b.name : '—';
        },

        changeBranchFilter(branchId) {
            this.activeBranchFilter = branchId;
            this.refreshStats();
            if (this.currentTab === 'batch') this.loadPendingCartridges();
            if (this.currentTab === 'return') this.loadAtVendorAndReady();
            if (this.currentTab === 'registry') this.loadRegistry();
        },

        // Управление филиалами в Настройках
        branchModalOpen: false,
        branchForm: { id: null, name: '', code: '', address: '', notes: '' },
        isSavingBranch: false,

        openCreateBranch() {
            this.branchForm = { id: null, name: '', code: '', address: '', notes: '' };
            this.branchModalOpen = true;
        },

        openEditBranch(b) {
            this.branchForm = { id: b.id, name: b.name, code: b.code || '', address: b.address || '', notes: b.notes || '' };
            this.branchModalOpen = true;
        },

        async saveBranch() {
            if (!this.branchForm.name.trim()) {
                this.showToast('Введите наименование филиала', 'error');
                return;
            }
            this.isSavingBranch = true;
            try {
                const isEdit = !!this.branchForm.id;
                const url = isEdit ? `/api/branches/${this.branchForm.id}` : '/api/branches';
                const method = isEdit ? 'PUT' : 'POST';

                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.branchForm)
                });

                if (res.ok) {
                    this.showToast(isEdit ? 'Филиал обновлен' : 'Филиал создан', 'success');
                    this.branchModalOpen = false;
                    await this.loadBranches();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка сохранения филиала', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            } finally {
                this.isSavingBranch = false;
            }
        },

        async deleteBranch(id) {
            if (!confirm('Удалить этот филиал?')) return;
            try {
                const res = await fetch(`/api/branches/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Филиал удален', 'success');
                    await this.loadBranches();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка удаления филиала', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        // ==========================================
        // УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (В НАСТРОЙКАХ)
        // ==========================================
        appUsers: [],
        isLoadingUsers: false,
        userModalOpen: false,
        isSavingUser: false,
        userForm: {
            id: null,
            username: '',
            full_name: '',
            password: '',
            auth_type: 'local',
            role: 'user',
            branch_id: '',
            is_active: true
        },

        async loadAppUsers() {
            this.isLoadingUsers = true;
            try {
                const res = await fetch('/api/app-users');
                if (res.ok) {
                    this.appUsers = await res.json();
                }
            } catch (e) {
                console.error(e);
            } finally {
                this.isLoadingUsers = false;
            }
        },

        openCreateUser() {
            this.userForm = {
                id: null,
                username: '',
                full_name: '',
                password: '',
                auth_type: 'local',
                role: 'user',
                branch_id: '',
                is_active: true
            };
            this.userModalOpen = true;
        },

        openEditUser(u) {
            this.userForm = {
                id: u.id,
                username: u.username,
                full_name: u.full_name,
                password: '',
                auth_type: u.auth_type,
                role: u.role,
                branch_id: u.branch_id || '',
                is_active: u.is_active
            };
            this.userModalOpen = true;
        },

        async saveUser() {
            if (!this.userForm.username.trim() || !this.userForm.full_name.trim()) {
                this.showToast('Заполните логин и ФИО', 'error');
                return;
            }
            if (!this.userForm.id && this.userForm.auth_type === 'local' && !this.userForm.password) {
                this.showToast('Задайте пароль для локального пользователя', 'error');
                return;
            }

            this.isSavingUser = true;
            try {
                const isEdit = !!this.userForm.id;
                const url = isEdit ? `/api/app-users/${this.userForm.id}` : '/api/app-users';
                const method = isEdit ? 'PUT' : 'POST';

                const payload = { ...this.userForm };
                payload.branch_id = payload.branch_id ? parseInt(payload.branch_id) : null;
                if (isEdit && !payload.password) delete payload.password;

                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    this.showToast(isEdit ? 'Пользователь обновлен' : 'Пользователь создан', 'success');
                    this.userModalOpen = false;
                    await this.loadAppUsers();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка сохранения пользователя', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            } finally {
                this.isSavingUser = false;
            }
        },

        async toggleUserActive(u) {
            try {
                const res = await fetch(`/api/app-users/${u.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: !u.is_active })
                });
                if (res.ok) {
                    this.showToast(u.is_active ? 'Пользователь заблокирован' : 'Пользователь разблокирован', 'success');
                    await this.loadAppUsers();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка изменения статуса', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        async deleteUser(id) {
            if (!confirm('Удалить этого пользователя?')) return;
            try {
                const res = await fetch(`/api/app-users/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Пользователь удален', 'success');
                    await this.loadAppUsers();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка удаления', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        // ==========================================
        // ОБНОВЛЕНИЕ СТАТИСТИКИ
        // ==========================================
        async refreshStats() {
            try {
                let url = '/api/cartridges?limit=500';
                if (this.activeBranchFilter) {
                    url += `&branch_id=${this.activeBranchFilter}`;
                }
                const res = await fetch(url);
                if (res.ok) {
                    const data = await res.json();
                    this.stats.total = data.length;
                    this.stats.pending = data.filter(c => c.status === 'pending_vendor').length;
                    this.stats.at_vendor = data.filter(c => c.status === 'at_vendor').length;
                    this.stats.ready = data.filter(c => c.status === 'ready_for_pickup').length;
                    this.stats.in_use = data.filter(c => c.status === 'in_use').length;
                }
            } catch (e) {
                console.error('Error refreshing stats:', e);
            }
        },

        // ==========================================
        // 1. ЭКРАН ПРИЕМКИ
        // ==========================================
        acceptance: {
            markerInput: '',
            isSearching: false,
            found: false,
            cartridge: null,
            form: {
                marker_label: '',
                qr_code: '',
                model: '',
                cabinet: '',
                branch_id: null,
                current_user_id: '',
                notes: '',
                action_required: 'Заправка'
            },
            userSearch: '',
            userResults: [],
            selectedUser: null,
            isSearchingUsers: false,
            isSubmitting: false
        },

        initAcceptanceBranch() {
            if (this.currentUser) {
                this.acceptance.form.branch_id = this.currentUser.branch_id || (this.branches[0]?.id || null);
            }
        },

        async searchMarkerAcceptance() {
            const query = this.acceptance.markerInput.trim();
            if (!query) return;

            this.acceptance.isSearching = true;
            try {
                const res = await fetch(`/api/cartridges/search/quick?marker=${encodeURIComponent(query)}`);
                const data = await res.json();
                if (data.found && data.cartridge) {
                    this.acceptance.found = true;
                    this.acceptance.cartridge = data.cartridge;
                    this.acceptance.form.marker_label = data.cartridge.marker_label;
                    this.acceptance.form.qr_code = data.cartridge.qr_code || '';
                    this.acceptance.form.model = data.cartridge.model;
                    this.acceptance.form.cabinet = data.cartridge.cabinet;
                    this.acceptance.form.branch_id = data.cartridge.branch_id || this.currentUser?.branch_id || null;
                    this.acceptance.form.current_user_id = data.cartridge.current_user_id || '';
                    this.acceptance.selectedUser = data.cartridge.current_user || null;
                    if (data.cartridge.current_user) {
                        this.acceptance.userSearch = data.cartridge.current_user.display_name;
                    }
                    this.showToast(`Найден картридж: ${data.cartridge.marker_label} (${data.cartridge.model})`, 'info');
                } else {
                    this.acceptance.found = false;
                    this.acceptance.cartridge = null;
                    this.acceptance.form.marker_label = query;
                    this.acceptance.form.model = '';
                    this.acceptance.form.cabinet = '';
                    this.acceptance.form.qr_code = '';
                    this.initAcceptanceBranch();
                    this.acceptance.form.current_user_id = '';
                    this.acceptance.selectedUser = null;
                    this.acceptance.userSearch = '';
                    this.showToast(`Картридж с меткой "${query}" не найден. Заполните данные для регистрации.`, 'info');
                }
            } catch (e) {
                this.showToast('Ошибка поиска картриджа', 'error');
            } finally {
                this.acceptance.isSearching = false;
            }
        },

        async searchUsers(query) {
            if (!query || query.length < 2) {
                this.acceptance.userResults = [];
                return;
            }
            this.acceptance.isSearchingUsers = true;
            try {
                const res = await fetch(`/api/users?q=${encodeURIComponent(query)}&limit=10`);
                if (res.ok) {
                    this.acceptance.userResults = await res.json();
                }
            } catch (e) {
                console.error(e);
            } finally {
                this.acceptance.isSearchingUsers = false;
            }
        },

        selectUser(user) {
            this.acceptance.selectedUser = user;
            this.acceptance.form.current_user_id = user.samaccountname;
            this.acceptance.userSearch = `${user.display_name} (${user.cabinet || 'нет кабинета'})`;
            if (user.cabinet && !this.acceptance.form.cabinet) {
                this.acceptance.form.cabinet = user.cabinet;
            }
            this.acceptance.userResults = [];
        },

        clearSelectedUser() {
            this.acceptance.selectedUser = null;
            this.acceptance.form.current_user_id = '';
            this.acceptance.userSearch = '';
        },

        async submitAcceptance() {
            if (!this.acceptance.form.marker_label.trim()) {
                this.showToast('Укажите надпись маркером', 'error');
                return;
            }
            if (!this.acceptance.form.model.trim()) {
                this.showToast('Укажите модель картриджа', 'error');
                return;
            }
            if (!this.acceptance.form.cabinet.trim()) {
                this.showToast('Укажите кабинет', 'error');
                return;
            }

            // Автоматически фиксируем филиал из профиля, если у пользователя назначен конкретный
            if (this.currentUser && this.currentUser.branch_id) {
                this.acceptance.form.branch_id = this.currentUser.branch_id;
            }

            this.acceptance.isSubmitting = true;
            try {
                const res = await fetch('/api/cartridges/accept', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.acceptance.form)
                });

                if (res.ok) {
                    const cart = await res.json();
                    this.showToast(`Картридж "${cart.marker_label}" принят. Статус: Ожидает заправщика`, 'success');
                    // Сброс формы
                    this.acceptance.markerInput = '';
                    this.acceptance.found = false;
                    this.acceptance.cartridge = null;
                    this.acceptance.form = {
                        marker_label: '',
                        qr_code: '',
                        model: '',
                        cabinet: '',
                        branch_id: this.currentUser?.branch_id || (this.branches[0]?.id || null),
                        current_user_id: '',
                        notes: '',
                        action_required: 'Заправка'
                    };
                    this.clearSelectedUser();
                    await this.refreshStats();
                    this.loadPendingCartridges();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка приемки', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка отправки формы', 'error');
            } finally {
                this.acceptance.isSubmitting = false;
            }
        },

        // ==========================================
        // 2. ЭКРАН ФОРМИРОВАНИЯ АКТА
        // ==========================================
        batch: {
            pendingCartridges: [],
            selectedIds: [],
            vendorName: '',
            actionRequired: 'Заправка',
            notes: '',
            isLoading: false,
            isSubmitting: false,
            history: []
        },

        async loadPendingCartridges() {
            this.batch.isLoading = true;
            try {
                let url = '/api/cartridges?status=pending_vendor&limit=200';
                if (this.activeBranchFilter) {
                    url += `&branch_id=${this.activeBranchFilter}`;
                }
                const res = await fetch(url);
                if (res.ok) {
                    this.batch.pendingCartridges = await res.json();
                    this.batch.selectedIds = this.batch.pendingCartridges.map(c => c.id);
                }
                if (!this.batch.vendorName) {
                    this.batch.vendorName = this.settings.default_vendor || 'ООО «СервисПринт»';
                }
            } catch (e) {
                this.showToast('Ошибка загрузки картриджей для акта', 'error');
            } finally {
                this.batch.isLoading = false;
            }
        },

        toggleSelectAllPending() {
            if (this.batch.selectedIds.length === this.batch.pendingCartridges.length) {
                this.batch.selectedIds = [];
            } else {
                this.batch.selectedIds = this.batch.pendingCartridges.map(c => c.id);
            }
        },

        async createBatch() {
            if (this.batch.selectedIds.length === 0) {
                this.showToast('Выберите хотя бы один картридж для включения в акт', 'error');
                return;
            }
            if (!this.batch.vendorName.trim()) {
                this.showToast('Укажите сервисный центр / поставщика', 'error');
                return;
            }

            this.batch.isSubmitting = true;
            try {
                const payload = {
                    cartridge_ids: this.batch.selectedIds,
                    vendor_name: this.batch.vendorName.trim(),
                    branch_id: this.currentUser?.branch_id || (this.activeBranchFilter ? parseInt(this.activeBranchFilter) : null),
                    action_required: this.batch.actionRequired,
                    notes: this.batch.notes
                };

                const res = await fetch('/api/batches', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    const batchData = await res.json();
                    this.showToast(`Акт № ${batchData.act_number} сформирован! Открываем печатную форму...`, 'success');
                    window.open(`/print/act/${batchData.id}`, '_blank');
                    await this.refreshStats();
                    await this.loadPendingCartridges();
                    this.loadBatchesHistory();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка создания акта', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения при создании акта', 'error');
            } finally {
                this.batch.isSubmitting = false;
            }
        },

        async loadBatchesHistory() {
            try {
                let url = '/api/batches?limit=50';
                if (this.activeBranchFilter) {
                    url += `&branch_id=${this.activeBranchFilter}`;
                }
                const res = await fetch(url);
                if (res.ok) {
                    this.batch.history = await res.json();
                }
            } catch (e) {
                console.error(e);
            }
        },

        printBatch(batchId) {
            window.open(`/print/act/${batchId}`, '_blank');
        },

        // ==========================================
        // 3. ЭКРАН ВОЗВРАТА И РАССЫЛКИ WHATSAPP
        // ==========================================
        vendorReturn: {
            atVendorList: [],
            selectedReturnIds: [],
            readyList: [],
            isLoading: false,
            isReturning: false,
            isNotifying: false,
            resultsModalOpen: false,
            resultsData: null
        },

        async loadAtVendorAndReady() {
            this.vendorReturn.isLoading = true;
            try {
                let urlVendor = '/api/cartridges?status=at_vendor&limit=200';
                let urlReady = '/api/cartridges?status=ready_for_pickup&limit=200';
                if (this.activeBranchFilter) {
                    urlVendor += `&branch_id=${this.activeBranchFilter}`;
                    urlReady += `&branch_id=${this.activeBranchFilter}`;
                }

                const [resVendor, resReady] = await Promise.all([
                    fetch(urlVendor),
                    fetch(urlReady)
                ]);

                if (resVendor.ok) {
                    this.vendorReturn.atVendorList = await resVendor.json();
                    this.vendorReturn.selectedReturnIds = this.vendorReturn.atVendorList.map(c => c.id);
                }
                if (resReady.ok) {
                    this.vendorReturn.readyList = await resReady.json();
                }
            } catch (e) {
                this.showToast('Ошибка загрузки списков заправки', 'error');
            } finally {
                this.vendorReturn.isLoading = false;
            }
        },

        toggleSelectAllReturn() {
            if (this.vendorReturn.selectedReturnIds.length === this.vendorReturn.atVendorList.length) {
                this.vendorReturn.selectedReturnIds = [];
            } else {
                this.vendorReturn.selectedReturnIds = this.vendorReturn.atVendorList.map(c => c.id);
            }
        },

        async submitReturnFromVendor() {
            if (this.vendorReturn.selectedReturnIds.length === 0) {
                this.showToast('Отметьте картриджи, которые привез заправщик', 'error');
                return;
            }

            this.vendorReturn.isReturning = true;
            try {
                const res = await fetch('/api/cartridges/return-vendor', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cartridge_ids: this.vendorReturn.selectedReturnIds })
                });

                if (res.ok) {
                    const data = await res.json();
                    this.showToast(data.message, 'success');
                    await this.refreshStats();
                    await this.loadAtVendorAndReady();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка при возврате', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            } finally {
                this.vendorReturn.isReturning = false;
            }
        },

        async sendWhatsAppNotifications() {
            if (this.vendorReturn.readyList.length === 0) {
                this.showToast('Нет картриджей в статусе «Готов к выдаче»', 'info');
                return;
            }

            if (!confirm(`Отправить персональные WhatsApp-оповещения владельцам ${this.vendorReturn.readyList.length} картридж(ей)?`)) {
                return;
            }

            this.vendorReturn.isNotifying = true;
            try {
                const cartIds = this.vendorReturn.readyList.map(c => c.id);
                const res = await fetch('/api/notifications/whatsapp/ready', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ cartridge_ids: cartIds })
                });

                if (res.ok) {
                    const data = await res.json();
                    this.vendorReturn.resultsData = data;
                    this.vendorReturn.resultsModalOpen = true;
                    this.showToast(data.message, data.failed_count === 0 ? 'success' : 'info');
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка рассылки', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка шлюза WhatsApp', 'error');
            } finally {
                this.vendorReturn.isNotifying = false;
            }
        },

        // РУЧНАЯ ВЫДАЧА ИЗ ОКНА ОТЧЕТА WHATSAPP
        async issueFromWhatsAppReport(item) {
            try {
                const res = await fetch(`/api/cartridges/${item.cartridge_id}/issue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: 'Выдан вручную (номер WhatsApp не указан или ошибка отправки)' })
                });

                if (res.ok) {
                    item.manual_issued = true;
                    this.showToast(`Картридж "${item.marker}" успешно отмечен как выдан!`, 'success');
                    await this.refreshStats();
                    await this.loadAtVendorAndReady();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка выдачи', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        // ==========================================
        // 4. ЭКРАН ВЫДАЧИ
        // ==========================================
        issue: {
            markerInput: '',
            cartridge: null,
            isSearching: false,
            isIssuing: false,
            notes: ''
        },

        async searchCartridgeForIssue() {
            const query = this.issue.markerInput.trim();
            if (!query) return;

            this.issue.isSearching = true;
            try {
                const res = await fetch(`/api/cartridges/search/quick?marker=${encodeURIComponent(query)}`);
                const data = await res.json();
                if (data.found && data.cartridge) {
                    this.issue.cartridge = data.cartridge;
                } else {
                    this.issue.cartridge = null;
                    this.showToast(`Картридж "${query}" не найден в базе данных`, 'error');
                }
            } catch (e) {
                this.showToast('Ошибка поиска картриджа', 'error');
            } finally {
                this.issue.isSearching = false;
            }
        },

        async submitIssue() {
            if (!this.issue.cartridge) return;

            this.issue.isIssuing = true;
            try {
                const res = await fetch(`/api/cartridges/${this.issue.cartridge.id}/issue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: this.issue.notes })
                });

                if (res.ok) {
                    this.showToast(`Картридж "${this.issue.cartridge.marker_label}" выдан сотруднику. Статус: В работе`, 'success');
                    this.issue.cartridge = null;
                    this.issue.markerInput = '';
                    this.issue.notes = '';
                    await this.refreshStats();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка выдачи', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            } finally {
                this.issue.isIssuing = false;
            }
        },

        // ==========================================
        // 5. РЕЕСТР КАРТРИДЖЕЙ
        // ==========================================
        registry: {
            list: [],
            searchQuery: '',
            filterStatus: '',
            isLoading: false,
            selectedCartridge: null,
            historyModalOpen: false,
            editModalOpen: false,
            createModalOpen: false,
            editForm: {
                id: null,
                marker_label: '',
                qr_code: '',
                model: '',
                cabinet: '',
                branch_id: null,
                status: 'in_use',
                notes: ''
            },
            createForm: {
                marker_label: '',
                qr_code: '',
                model: '',
                cabinet: '',
                branch_id: null,
                status: 'in_use',
                notes: ''
            }
        },

        async loadRegistry() {
            this.registry.isLoading = true;
            try {
                let url = '/api/cartridges?limit=300';
                if (this.registry.filterStatus) {
                    url += `&status=${this.registry.filterStatus}`;
                }
                if (this.activeBranchFilter) {
                    url += `&branch_id=${this.activeBranchFilter}`;
                }
                if (this.registry.searchQuery.trim()) {
                    url += `&q=${encodeURIComponent(this.registry.searchQuery.trim())}`;
                }
                const res = await fetch(url);
                if (res.ok) {
                    this.registry.list = await res.json();
                }
            } catch (e) {
                this.showToast('Ошибка загрузки реестра', 'error');
            } finally {
                this.registry.isLoading = false;
            }
        },

        async viewHistory(cartId) {
            try {
                const res = await fetch(`/api/cartridges/${cartId}`);
                if (res.ok) {
                    this.registry.selectedCartridge = await res.json();
                    this.registry.historyModalOpen = true;
                }
            } catch (e) {
                this.showToast('Ошибка загрузки истории', 'error');
            }
        },

        openEditModal(cart) {
            this.registry.editForm = {
                id: cart.id,
                marker_label: cart.marker_label,
                qr_code: cart.qr_code || '',
                model: cart.model,
                cabinet: cart.cabinet,
                branch_id: cart.branch_id || '',
                status: cart.status,
                notes: cart.notes || ''
            };
            this.registry.editModalOpen = true;
        },

        async saveEdit() {
            try {
                const payload = { ...this.registry.editForm };
                payload.branch_id = payload.branch_id ? parseInt(payload.branch_id) : null;

                const res = await fetch(`/api/cartridges/${this.registry.editForm.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    this.showToast('Данные картриджа обновлены', 'success');
                    this.registry.editModalOpen = false;
                    await this.loadRegistry();
                    await this.refreshStats();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка сохранения', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        async deleteCartridge(cartId) {
            if (!confirm('Вы уверены, что хотите удалить этот картридж и всю его историю?')) return;

            try {
                const res = await fetch(`/api/cartridges/${cartId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Картридж удален', 'success');
                    await this.loadRegistry();
                    await this.refreshStats();
                }
            } catch (e) {
                this.showToast('Ошибка удаления', 'error');
            }
        },

        async saveNewCartridge() {
            if (!this.registry.createForm.marker_label || !this.registry.createForm.model || !this.registry.createForm.cabinet) {
                this.showToast('Заполните обязательные поля (Маркер, Модель, Кабинет)', 'error');
                return;
            }
            try {
                const payload = { ...this.registry.createForm };
                payload.branch_id = this.currentUser?.branch_id || (payload.branch_id ? parseInt(payload.branch_id) : null);

                const res = await fetch('/api/cartridges', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    this.showToast('Картридж успешно добавлен в реестр', 'success');
                    this.registry.createModalOpen = false;
                    this.registry.createForm = { marker_label: '', qr_code: '', model: '', cabinet: '', branch_id: null, status: 'in_use', notes: '' };
                    await this.loadRegistry();
                    await this.refreshStats();
                } else {
                    const err = await res.json();
                    this.showToast(err.detail || 'Ошибка создания', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения', 'error');
            }
        },

        // ==========================================
        // 6. МОДУЛЬ «НАСТРОЙКИ»
        // ==========================================
        settingsForm: {},
        isSavingSettings: false,
        showPassword: false,

        ldapTesting: false,
        ldapTestResult: null,
        ldapSyncing: false,
        ldapSyncResult: null,

        waStatus: {
            connected: false,
            state: 'unknown',
            message: 'Статус не проверен'
        },
        waChecking: false,
        personalWaStatus: {
            connected: false,
            state: 'unknown',
            message: 'Не проверен'
        },
        personalWaChecking: false,
        operatorsWaList: [],
        operatorsWaLoading: false,
        waQrModalOpen: false,
        waQrBase64: '',
        waQrPairingCode: '',
        waQrError: '',
        waQrLoading: false,
        waQrTargetTitle: '',
        waQrTargetInstance: '',
        waQrTargetUserId: null,
        waTestPhone: '',
        waTestInstance: '',
        waTestSending: false,
        waTestResult: null,

        async loadSettings() {
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    this.settings = await res.json();
                    this.settingsForm = { ...this.settings };
                }
            } catch (e) {
                console.error('Error loading settings:', e);
            }
        },

        async saveSettings() {
            this.isSavingSettings = true;
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ settings: this.settingsForm })
                });

                if (res.ok) {
                    const data = await res.json();
                    this.settings = { ...data.settings };
                    this.settingsForm = { ...this.settings };
                    this.showToast('Настройки успешно сохранены!', 'success');
                    if (this.settingsForm.wa_mode === 'individual') {
                        await this.loadOperatorsWaStatus();
                    }
                } else {
                    const errData = await res.json().catch(() => ({}));
                    const detail = errData.detail || 'Ошибка сохранения настроек';
                    this.showToast(detail, 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения при сохранении', 'error');
            } finally {
                this.isSavingSettings = false;
            }
        },

        async setWaMode(mode) {
            this.settingsForm.wa_mode = mode;
            if (this.currentUser?.role === 'superadmin') {
                await this.saveSettings();
            } else {
                this.showToast('Только Супер администратор может изменять глобальный режим WhatsApp', 'warning');
            }
            if (mode === 'individual') {
                await this.loadOperatorsWaStatus();
            }
        },

        async testLdap() {
            this.ldapTesting = true;
            this.ldapTestResult = null;
            try {
                await this.saveSettings();

                const res = await fetch('/api/settings/ldap/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        host: this.settingsForm.ad_host,
                        base_dn: this.settingsForm.ad_base_dn,
                        bind_user: this.settingsForm.ad_bind_user,
                        bind_password: this.settingsForm.ad_bind_password
                    })
                });

                this.ldapTestResult = await res.json();
            } catch (e) {
                this.ldapTestResult = { success: false, message: 'Сетевая ошибка обращения к API: ' + (e.message || e) };
            } finally {
                this.ldapTesting = false;
            }
        },

        async syncLdap() {
            this.ldapSyncing = true;
            this.ldapSyncResult = null;
            try {
                await this.saveSettings();

                const res = await fetch('/api/settings/ldap/sync', { method: 'POST' });
                this.ldapSyncResult = await res.json();
                if (this.ldapSyncResult.success) {
                    this.showToast(`Синхронизировано пользователей: ${this.ldapSyncResult.synced_count}`, 'success');
                }
            } catch (e) {
                this.ldapSyncResult = { success: false, message: 'Ошибка вызова синхронизации: ' + (e.message || e) };
            } finally {
                this.ldapSyncing = false;
            }
        },

        async checkWaStatus(instanceName = null) {
            this.waChecking = true;
            try {
                let url = '/api/settings/wa/status';
                if (instanceName) url += `?instance_name=${encodeURIComponent(instanceName)}`;
                const res = await fetch(url, { headers: this.authHeaders() });
                if (res.ok) {
                    this.waStatus = await res.json();
                } else {
                    this.waStatus = { connected: false, state: 'error', message: 'Ошибка ответа шлюза' };
                }
            } catch (e) {
                this.waStatus = { connected: false, state: 'unreachable', message: 'Шлюз Evolution API недоступен' };
            } finally {
                this.waChecking = false;
            }
        },

        async checkPersonalWaStatus() {
            if (!this.currentUser) return;
            this.personalWaChecking = true;
            try {
                const inst = this.currentUser.wa_instance_name || `operator_${this.currentUser.id}`;
                const res = await fetch(`/api/settings/wa/status?instance_name=${encodeURIComponent(inst)}`, {
                    headers: this.authHeaders()
                });
                if (res.ok) {
                    this.personalWaStatus = await res.json();
                } else {
                    this.personalWaStatus = { connected: false, state: 'error', message: 'Ошибка проверки' };
                }
            } catch (e) {
                this.personalWaStatus = { connected: false, state: 'unreachable', message: 'Шлюз недоступен' };
            } finally {
                this.personalWaChecking = false;
            }
        },

        async loadOperatorsWaStatus() {
            if (this.currentUser?.role !== 'superadmin') {
                await this.checkPersonalWaStatus();
                return;
            }
            this.operatorsWaLoading = true;
            try {
                const res = await fetch('/api/settings/wa/operators-status', {
                    headers: this.authHeaders()
                });
                if (res.ok) {
                    this.operatorsWaList = await res.json();
                    // Если инстанс для теста еще не выбран, выбираем первый подключенный
                    if (!this.waTestInstance && this.operatorsWaList.length > 0) {
                        const connectedOp = this.operatorsWaList.find(op => op.connected);
                        if (connectedOp) {
                            this.waTestInstance = connectedOp.instance_name;
                        }
                    }
                }
            } catch (e) {
                console.error('Error loading operators WA status:', e);
            } finally {
                this.operatorsWaLoading = false;
            }
        },

        openPersonalWaModal() {
            if (!this.currentUser) return;
            const inst = this.currentUser.wa_instance_name || `operator_${this.currentUser.id}`;
            this.getWaQrCode(false, inst, this.currentUser.id, `Личный WhatsApp: ${this.currentUser.full_name}`);
        },

        async getWaQrCode(isReset = false, instanceName = null, userId = null, targetTitle = null) {
            // Если текущий пользователь не Супер администратор, он имеет доступ ТОЛЬКО к своему аккаунту
            if (this.currentUser?.role !== 'superadmin') {
                instanceName = this.currentUser.wa_instance_name || `operator_${this.currentUser.id}`;
                userId = this.currentUser.id;
                targetTitle = `Личный WhatsApp: ${this.currentUser.full_name}`;
            }

            this.waQrLoading = true;
            this.waQrModalOpen = true;
            this.waQrBase64 = '';
            this.waQrPairingCode = '';
            this.waQrError = '';
            this.waQrTargetInstance = instanceName || '';
            this.waQrTargetUserId = userId || null;
            this.waQrTargetTitle = targetTitle || (instanceName ? `Инстанс: ${instanceName}` : (this.settingsForm.wa_mode === 'individual' ? `Личный WhatsApp (${this.currentUser?.full_name})` : 'Общий WhatsApp шлюз'));

            try {
                let endpoint = isReset ? '/api/settings/wa/reset' : '/api/settings/wa/qr';
                const params = new URLSearchParams();
                if (instanceName) params.append('instance_name', instanceName);
                if (userId) params.append('user_id', userId);
                if (params.toString()) {
                    endpoint += '?' + params.toString();
                }

                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: this.authHeaders()
                });
                const data = await res.json();
                if (data.already_connected) {
                    this.waQrModalOpen = false;
                    this.showToast(data.message || 'WhatsApp уже успешно подключен!', 'success');
                    await this.checkWaStatus();
                    await this.checkPersonalWaStatus();
                    if (this.settingsTab === 'whatsapp') {
                        await this.loadOperatorsWaStatus();
                    }
                } else if (data.success && data.qr_base64) {
                    this.waQrBase64 = data.qr_base64;
                    this.waQrPairingCode = data.pairing_code || '';
                    this.showToast(data.message || 'QR-код готов к сканированию', 'info');
                } else {
                    this.waQrError = data.message || 'Шлюз не вернул QR-код. Возможно, сессия еще инициализируется.';
                    this.showToast(this.waQrError, 'warning');
                }
            } catch (e) {
                this.waQrError = 'Ошибка соединения со шлюзом: ' + e.message;
                this.showToast(this.waQrError, 'error');
            } finally {
                this.waQrLoading = false;
            }
        },

        async sendWaTestMessage(instanceName = null) {
            if (!this.waTestPhone.trim()) {
                this.showToast('Введите номер телефона для теста', 'error');
                return;
            }
            this.waTestSending = true;
            this.waTestResult = null;
            try {
                let targetInst = instanceName || this.waTestInstance || null;
                if (!targetInst && this.settingsForm.wa_mode === 'shared') {
                    targetInst = this.settingsForm.wa_instance_name || 'cartridge_bot';
                }
                const res = await fetch('/api/settings/wa/test', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        phone: this.waTestPhone,
                        instance_name: targetInst
                    })
                });
                this.waTestResult = await res.json();
                if (this.waTestResult.success) {
                    this.showToast(this.waTestResult.message || 'Тестовое сообщение отправлено в WhatsApp!', 'success');
                } else {
                    this.showToast(this.waTestResult.message || 'Ошибка отправки тестового сообщения', 'error');
                }
            } catch (e) {
                this.waTestResult = { success: false, message: 'Ошибка выполнения запроса: ' + (e.message || e) };
                this.showToast(this.waTestResult.message, 'error');
            } finally {
                this.waTestSending = false;
            }
        },

        // ==========================================
        // 7. МОДАЛЬНОЕ ОКНО QR-СКАНЕРА КАМЕРЫ
        // ==========================================
        qrModalOpen: false,
        qrTargetMode: 'acceptance', // 'acceptance' | 'issue' | 'search'

        openCameraScanner(targetMode) {
            this.qrTargetMode = targetMode;
            this.qrModalOpen = true;

            setTimeout(() => {
                window.QRScannerModule.start(
                    'qr-reader',
                    (decodedText) => {
                        this.handleQrScanResult(decodedText);
                    },
                    (error) => {
                        this.showToast('Ошибка камеры: ' + (error.message || error), 'error');
                        this.closeCameraScanner();
                    }
                );
            }, 300);
        },

        closeCameraScanner() {
            window.QRScannerModule.stop();
            this.qrModalOpen = false;
        },

        async handleQrScanResult(decodedText) {
            this.closeCameraScanner();
            this.showToast(`Распознан код: ${decodedText}`, 'info');

            if (this.qrTargetMode === 'acceptance') {
                try {
                    const res = await fetch(`/api/cartridges/search/quick?qr=${encodeURIComponent(decodedText)}&marker=${encodeURIComponent(decodedText)}`);
                    const data = await res.json();
                    if (data.found && data.cartridge) {
                        this.acceptance.found = true;
                        this.acceptance.cartridge = data.cartridge;
                        this.acceptance.form.marker_label = data.cartridge.marker_label;
                        this.acceptance.form.qr_code = data.cartridge.qr_code || decodedText;
                        this.acceptance.form.model = data.cartridge.model;
                        this.acceptance.form.cabinet = data.cartridge.cabinet;
                        this.acceptance.form.branch_id = data.cartridge.branch_id || this.currentUser?.branch_id || null;
                        this.acceptance.form.current_user_id = data.cartridge.current_user_id || '';
                        this.acceptance.selectedUser = data.cartridge.current_user || null;
                        this.showToast(`Картридж найден: ${data.cartridge.marker_label}`, 'success');
                    } else {
                        this.acceptance.form.marker_label = decodedText;
                        this.acceptance.form.qr_code = decodedText;
                        this.acceptance.markerInput = decodedText;
                        this.showToast(`Новый картридж со считанным кодом: ${decodedText}`, 'info');
                    }
                } catch (e) {
                    this.showToast('Ошибка проверки кода', 'error');
                }
            } else if (this.qrTargetMode === 'issue') {
                this.issue.markerInput = decodedText;
                this.searchCartridgeForIssue();
            } else if (this.qrTargetMode === 'search') {
                this.registry.searchQuery = decodedText;
                this.loadRegistry();
            }
        },

        // ==========================================
        // 8. РАЗДЕЛ ОТЧЕТОВ
        // ==========================================
        reports: {
            type: 'all', // 'all' | 'year' | 'month' | 'custom'
            branch_id: '',
            year: new Date().getFullYear(),
            month: new Date().getMonth() + 1,
            date_from: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
            date_to: new Date().toISOString().split('T')[0],
            loading: false,
            data: null,
            searchQuery: '',
            availableYears: [
                new Date().getFullYear(),
                new Date().getFullYear() - 1,
                new Date().getFullYear() - 2,
                new Date().getFullYear() - 3
            ],
            monthsList: [
                { id: 1, name: 'Январь' },
                { id: 2, name: 'Февраль' },
                { id: 3, name: 'Март' },
                { id: 4, name: 'Апрель' },
                { id: 5, name: 'Май' },
                { id: 6, name: 'Июнь' },
                { id: 7, name: 'Июль' },
                { id: 8, name: 'Август' },
                { id: 9, name: 'Сентябрь' },
                { id: 10, name: 'Октябрь' },
                { id: 11, name: 'Ноябрь' },
                { id: 12, name: 'Декабрь' }
            ]
        },

        initReportsTab() {
            if (this.currentUser?.branch_id) {
                this.reports.branch_id = this.currentUser.branch_id;
            } else if (!this.reports.branch_id && this.activeBranchFilter) {
                this.reports.branch_id = this.activeBranchFilter;
            }
            if (!this.reports.data) {
                this.fetchReport();
            }
        },

        async fetchReport() {
            this.reports.loading = true;
            try {
                const params = new URLSearchParams();
                params.append('report_type', this.reports.type);
                if (this.reports.branch_id) {
                    params.append('branch_id', this.reports.branch_id);
                }
                if (this.reports.type === 'year') {
                    params.append('year', this.reports.year);
                } else if (this.reports.type === 'month') {
                    params.append('year', this.reports.year);
                    params.append('month', this.reports.month);
                } else if (this.reports.type === 'custom') {
                    if (this.reports.date_from) params.append('date_from', this.reports.date_from);
                    if (this.reports.date_to) params.append('date_to', this.reports.date_to);
                }

                const res = await fetch(`/api/reports/data?${params.toString()}`);
                if (res.ok) {
                    const result = await res.json();
                    this.reports.data = result.report;
                } else {
                    const err = await res.json().catch(() => ({}));
                    this.showToast(err.detail || 'Ошибка формирования отчета', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения при формировании отчета', 'error');
            } finally {
                this.reports.loading = false;
            }
        },

        downloadReportExcel() {
            const params = new URLSearchParams();
            params.append('report_type', this.reports.type);
            if (this.reports.branch_id) {
                params.append('branch_id', this.reports.branch_id);
            }
            if (this.reports.type === 'year') {
                params.append('year', this.reports.year);
            } else if (this.reports.type === 'month') {
                params.append('year', this.reports.year);
                params.append('month', this.reports.month);
            } else if (this.reports.type === 'custom') {
                if (this.reports.date_from) params.append('date_from', this.reports.date_from);
                if (this.reports.date_to) params.append('date_to', this.reports.date_to);
            }

            this.showToast('Формирование файла Excel...', 'info');
            fetch(`/api/reports/export/excel?${params.toString()}`)
                .then(async res => {
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Ошибка выгрузки Excel');
                    }
                    let filename = `report_${this.reports.type}.xlsx`;
                    const disposition = res.headers.get('Content-Disposition');
                    if (disposition && disposition.includes("filename*=UTF-8''")) {
                        filename = decodeURIComponent(disposition.split("filename*=UTF-8''")[1].split(';')[0]);
                    } else if (disposition && disposition.includes('filename=')) {
                        filename = disposition.split('filename=')[1].split(';')[0].replace(/"/g, '');
                    }
                    return res.blob().then(blob => ({ blob, filename }));
                })
                .then(({ blob, filename }) => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                    this.showToast('Файл Excel успешно скачан!', 'success');
                })
                .catch(e => {
                    this.showToast(e.message || 'Не удалось скачать Excel', 'error');
                });
        },

        get filteredReportItems() {
            if (!this.reports.data || !this.reports.data.items) return [];
            const q = (this.reports.searchQuery || '').toLowerCase().trim();
            if (!q) return this.reports.data.items;

            return this.reports.data.items.filter(item => {
                if (this.reports.type === 'all') {
                    return (
                        (item.marker_label || '').toLowerCase().includes(q) ||
                        (item.model || '').toLowerCase().includes(q) ||
                        (item.cabinet || '').toLowerCase().includes(q) ||
                        (item.user_name || '').toLowerCase().includes(q) ||
                        (item.branch_name || '').toLowerCase().includes(q) ||
                        (item.status_label || '').toLowerCase().includes(q)
                    );
                } else {
                    return (
                        (item.cartridge_marker || '').toLowerCase().includes(q) ||
                        (item.cartridge_model || '').toLowerCase().includes(q) ||
                        (item.action || '').toLowerCase().includes(q) ||
                        (item.user_name || '').toLowerCase().includes(q) ||
                        (item.branch_name || '').toLowerCase().includes(q) ||
                        (item.details || '').toLowerCase().includes(q)
                    );
                }
            });
        },

        // Хелперы форматирования статусов
        formatStatus(status) {
            switch (status) {
                case 'in_use': return 'В работе';
                case 'pending_vendor': return 'Ожидает заправщика';
                case 'at_vendor': return 'На заправке';
                case 'ready_for_pickup': return 'Готов к выдаче';
                default: return status || '—';
            }
        },

        statusBadgeClass(status) {
            switch (status) {
                case 'in_use': return 'badge-in_use';
                case 'pending_vendor': return 'badge-pending_vendor';
                case 'at_vendor': return 'badge-at_vendor';
                case 'ready_for_pickup': return 'badge-ready_for_pickup';
                default: return 'bg-gray-100 text-gray-800';
            }
        },

        formatDateTime(isoStr) {
            if (!isoStr) return '—';
            try {
                const d = new Date(isoStr);
                return d.toLocaleString('ru-RU', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } catch (e) {
                return isoStr;
            }
        }
    };
}
