/**
 * Модуль интеграции сканера QR-кодов через веб-камеру или камеру смартфона (html5-qrcode)
 */
let html5QrCode = null;

window.QRScannerModule = {
    isOpen: false,

    start: function(elementId, onSuccessCallback, onErrorCallback) {
        if (typeof Html5Qrcode === "undefined") {
            alert("Библиотека сканирования QR-кодов еще загружается. Попробуйте снова через секунду.");
            return;
        }

        const qrRegionId = elementId || "qr-reader";
        if (html5QrCode && html5QrCode.isScanning) {
            html5QrCode.stop().catch(console.error);
        }

        html5QrCode = new Html5Qrcode(qrRegionId);
        this.isOpen = true;

        const config = {
            fps: 10,
            qrbox: { width: 250, height: 250 },
            aspectRatio: 1.0
        };

        // Запуск предпочтительно задней камеры (для телефонов) или доступной веб-камеры
        html5QrCode.start(
            { facingMode: "environment" },
            config,
            (decodedText, decodedResult) => {
                // Успешное считывание
                if (window.navigator && window.navigator.vibrate) {
                    window.navigator.vibrate(100);
                }
                this.stop();
                if (onSuccessCallback) {
                    onSuccessCallback(decodedText, decodedResult);
                }
            },
            (errorMessage) => {
                // Ошибки сканирования отдельных кадров (нормально при поиске)
            }
        ).catch((err) => {
            console.error("Camera access error:", err);
            this.isOpen = false;
            if (onErrorCallback) {
                onErrorCallback(err);
            } else {
                alert("Не удалось получить доступ к камере: " + (err.message || err));
            }
        });
    },

    stop: function() {
        if (html5QrCode && html5QrCode.isScanning) {
            html5QrCode.stop().then(() => {
                html5QrCode.clear();
                this.isOpen = false;
            }).catch(console.error);
        } else {
            this.isOpen = false;
        }
    }
};
