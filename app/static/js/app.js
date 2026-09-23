/**
 * Основное приложение Alpine.js для управления оборотом картриджей
 */

function cartridgeApp() {
    return {
        // Текущая навигация
        currentTab: 'acceptance', // 'acceptance' | 'batch' | 'return' | 'issue' | 'registry' | 'settings'
        settingsTab: 'ad',       // 'ad' | 'whatsapp' | 'general'
        batchSubTab: 'create',    // 'create' | 'history'

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
            await this.loadSettings();
            await this.refreshStats();
            this.loadPendingCartridges();
        },

        // Обновление статистики по статусам
        async refreshStats() {
            try {
                const res = await fetch('/api/cartridges?limit=500');
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
                const res = await fetch('/api/cartridges?status=pending_vendor&limit=200');
                if (res.ok) {
                    this.batch.pendingCartridges = await res.json();
                    // По умолчанию выбираем все
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
                    
                    // Открываем печатную форму в новом окне
                    window.open(`/print/act/${batchData.id}`, '_blank');

                    // Обновляем списки
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
                const res = await fetch('/api/batches?limit=50');
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
                const [resVendor, resReady] = await Promise.all([
                    fetch('/api/cartridges?status=at_vendor&limit=200'),
                    fetch('/api/cartridges?status=ready_for_pickup&limit=200')
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
                const res = await fetch('/api/notifications/whatsapp/ready', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cartridge_ids: null }) // все готовые
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
                status: 'in_use',
                notes: ''
            },
            createForm: {
                marker_label: '',
                qr_code: '',
                model: '',
                cabinet: '',
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
                status: cart.status,
                notes: cart.notes || ''
            };
            this.registry.editModalOpen = true;
        },

        async saveEdit() {
            try {
                const res = await fetch(`/api/cartridges/${this.registry.editForm.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.registry.editForm)
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
                const res = await fetch('/api/cartridges', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.registry.createForm)
                });
                if (res.ok) {
                    this.showToast('Картридж успешно добавлен в реестр', 'success');
                    this.registry.createModalOpen = false;
                    this.registry.createForm = { marker_label: '', qr_code: '', model: '', cabinet: '', status: 'in_use', notes: '' };
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
        waQrModalOpen: false,
        waQrBase64: '',
        waQrLoading: false,
        waTestPhone: '',
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
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: this.settingsForm })
                });

                if (res.ok) {
                    const data = await res.json();
                    this.settings = { ...data.settings };
                    this.showToast('Настройки успешно сохранены в базе данных!', 'success');
                } else {
                    this.showToast('Ошибка сохранения настроек', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка соединения при сохранении', 'error');
            } finally {
                this.isSavingSettings = false;
            }
        },

        async testLdap() {
            this.ldapTesting = true;
            this.ldapTestResult = null;
            try {
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
                this.ldapTestResult = { success: false, message: 'Сетевая ошибка обращения к API' };
            } finally {
                this.ldapTesting = false;
            }
        },

        async syncLdap() {
            this.ldapSyncing = true;
            this.ldapSyncResult = null;
            try {
                const res = await fetch('/api/settings/ldap/sync', { method: 'POST' });
                this.ldapSyncResult = await res.json();
                if (this.ldapSyncResult.success) {
                    this.showToast(`Синхронизировано пользователей: ${this.ldapSyncResult.synced_count}`, 'success');
                }
            } catch (e) {
                this.ldapSyncResult = { success: false, message: 'Ошибка вызова синхронизации' };
            } finally {
                this.ldapSyncing = false;
            }
        },

        async checkWaStatus() {
            this.waChecking = true;
            try {
                const res = await fetch('/api/settings/wa/status');
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

        async getWaQrCode() {
            this.waQrLoading = true;
            this.waQrModalOpen = true;
            this.waQrBase64 = '';
            try {
                const res = await fetch('/api/settings/wa/qr', { method: 'POST' });
                const data = await res.json();
                if (data.success && data.qr_base64) {
                    this.waQrBase64 = data.qr_base64;
                } else {
                    this.showToast(data.message || 'Не удалось сформировать QR-код', 'error');
                }
            } catch (e) {
                this.showToast('Ошибка обращения к шлюзу', 'error');
            } finally {
                this.waQrLoading = false;
            }
        },

        async sendWaTestMessage() {
            if (!this.waTestPhone.trim()) {
                this.showToast('Введите номер телефона для теста', 'error');
                return;
            }
            this.waTestSending = true;
            this.waTestResult = null;
            try {
                const res = await fetch('/api/settings/wa/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: this.waTestPhone })
                });
                this.waTestResult = await res.json();
                if (this.waTestResult.success) {
                    this.showToast('Тестовое сообщение отправлено в WhatsApp!', 'success');
                } else {
                    this.showToast('Ошибка отправки: ' + this.waTestResult.message, 'error');
                }
            } catch (e) {
                this.waTestResult = { success: false, message: 'Ошибка выполнения запроса' };
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
                // Ищем по QR или маркеру
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
                        this.acceptance.form.current_user_id = data.cartridge.current_user_id || '';
                        this.acceptance.selectedUser = data.cartridge.current_user || null;
                        this.showToast(`Картридж найден: ${data.cartridge.marker_label}`, 'success');
                    } else {
                        // Подставляем распознанный код в форму
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
