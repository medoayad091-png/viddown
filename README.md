# VidDown 🎬 — تحميل فيديو احترافي

تطبيق ويب لتحميل الفيديوهات من أكثر من 1000 موقع باستخدام `yt-dlp`.

## ✨ المميزات
- تحميل بدون علامة مائية
- دعم أكثر من 1000 موقع (يوتيوب، تيك توك، إنستغرام، تويتر...)
- اختيار الجودة (4K, 1080p, 720p...)
- تحميل MP3
- واجهة عربية احترافية
- الملفات تُحذف تلقائياً بعد 10 دقائق

---

## 🚀 رفع على Railway (مجاني)

### الخطوة 1: رفع على GitHub
```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/viddown.git
git push -u origin main
```

### الخطوة 2: إنشاء مشروع على Railway
1. اذهب إلى [railway.app](https://railway.app)
2. سجّل دخول بحساب GitHub
3. اضغط **"New Project"**
4. اختر **"Deploy from GitHub repo"**
5. اختر الـ repository الخاص بك
6. Railway سيكتشف الـ Dockerfile تلقائياً ويبدأ البناء

### الخطوة 3: إضافة Domain
1. في إعدادات المشروع → **"Networking"**
2. اضغط **"Generate Domain"**
3. ستحصل على رابط مجاني مثل: `https://viddown-production.up.railway.app`

---

## 📁 هيكل المشروع
```
viddown/
├── app.py           # Flask backend
├── requirements.txt # Python packages
├── Dockerfile       # Docker config
├── railway.json     # Railway config
└── templates/
    └── index.html   # Frontend
```

---

## 🔧 تشغيل محلياً
```bash
pip install -r requirements.txt
python app.py
# افتح http://localhost:5000
```

---

## ⚠️ تنبيه
يُرجى استخدام التطبيق بما يتوافق مع شروط الاستخدام وقوانين حقوق الملكية الفكرية.
