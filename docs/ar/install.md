# RPiDriver — دليل التثبيت

## المتطلبات

- Raspberry Pi 3B+ أو أحدث (يُوصى بنظام Raspberry Pi OS Bookworm / Bullseye)
- Python 3.10 أو أحدث
- اتصال بالإنترنت أثناء التثبيت

## التثبيت بأمر واحد

```bash
curl -fsSL https://ia.sa/rpidriver/install | sudo bash
```

سيقوم هذا السكريبت بما يلي:
1. التحقق من وجود Python 3.10 أو أحدث
2. تثبيت حزم النظام (`libusb`، `cups`، خطوط Noto، إلخ)
3. نسخ المستودع إلى `/opt/rpidriver`
4. إنشاء بيئة Python افتراضية وتثبيت جميع المتطلبات
5. كتابة ملف إعداد افتراضي في `/etc/rpidriver/config.ini`
6. تثبيت خدمة `systemd` تبدأ تلقائياً عند التشغيل
7. إعداد قواعد `udev` لتشغيل طابعات USB بدون صلاحيات `root`

---

## التثبيت اليدوي

### 1. استنساخ المستودع

```bash
git clone https://github.com/ibrahimaljuhani/rpidriver.git /opt/rpidriver
cd /opt/rpidriver
```

### 2. إنشاء البيئة الافتراضية

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. إنشاء ملف الإعداد

```bash
sudo mkdir -p /etc/rpidriver
sudo cp config/config.ini.tmpl /etc/rpidriver/config.ini
sudo nano /etc/rpidriver/config.ini
```

### 4. التشغيل يدوياً (للاختبار)

```bash
RPIDRIVER_CONFIG=/etc/rpidriver/config.ini .venv/bin/rpidriver
```

افتح `http://<عنوان-الـ-Pi>:8069` في متصفحك.

---

## إعداد Odoo POS

1. انتقل إلى **نقطة البيع ← الإعدادات ← التكوين**
2. فعّل **صندوق IoT**
3. اضبط عنوان IP الخاص بـ Raspberry Pi، المنفذ `8069`
4. احفظ وأعد التحميل — سيتصل Odoo بـ `/hw_proxy/hello` للتحقق من الاتصال

---

## إعداد الأجهزة

### طابعة ESC/POS

وصّل عبر USB. تتيح قواعد udev المثبّتة بالسكريبت الوصول تلقائياً.
عدّل `/etc/rpidriver/config.ini` ← `[escpos_driver]` إذا احتجت تغيير `paper_width`.

### الميزان (Toledo / Adam)

وصّل عبر محوّل USB-to-Serial. اضبط `port` و`baudrate` و`protocol` في `[scale_driver]`.

### شاشة العميل

وصّل عبر USB (يظهر Bixolon BCD-1000 كـ `/dev/ttyACM0`).
اضبط `port` في `[display_driver]`.

---

## إدارة الخدمة

```bash
# التحقق من الحالة
systemctl status rpidriver

# عرض السجلات المباشرة
journalctl -u rpidriver -f

# إعادة التشغيل بعد تغيير الإعدادات
sudo systemctl restart rpidriver

# التحديث إلى أحدث إصدار
sudo bash /opt/rpidriver/scripts/update.sh
```

---

## إعداد خط الطباعة العربي

لطباعة عربية صحيحة، ثبّت خط Noto Sans Arabic:

```bash
sudo apt-get install fonts-noto-extra
```

ثم اضبط في `/etc/rpidriver/config.ini`:

```ini
[escpos_driver]
arabic_font_path = /usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf
```

---

## استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `No ESC/POS printer found on USB` | تحقق من كابل USB؛ نفّذ `lsusb`؛ تحقق من قواعد udev |
| الطباعة العربية تظهر `???` | اضبط `arabic_font_path` في الإعدادات |
| الميزان يقرأ `0.0` دائماً | تحقق من `port` و`protocol` في `[scale_driver]` |
| Odoo لا يتصل | تأكد أن المنفذ 8069 غير محجوب بجدار حماية |

---

## الروابط

- الموقع: [ia.sa/rpidriver](https://ia.sa/rpidriver)
- الوثائق: [ia.sa/rpidriver/docs](https://ia.sa/rpidriver/docs)
- الدعم: [info@ia.sa](mailto:info@ia.sa)

---

## الترخيص

AGPL-3.0 — مثل [pywebdriver](https://github.com/akretion/pywebdriver) (Akretion).  
ترخيص تجاري متاح: [info@ia.sa](mailto:info@ia.sa)
