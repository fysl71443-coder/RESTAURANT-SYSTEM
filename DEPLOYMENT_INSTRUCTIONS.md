# 🚀 تعليمات نشر نظام POS الجديد

## 📦 ملخص التغييرات

تم تطوير نظام POS جديد مع الميزات التالية:

### ✨ الميزات الجديدة:
- **واجهات منفصلة** لـ China Town و Palace India
- **تكامل مع المنيو** - عرض الفئات والوجبات من قاعدة البيانات
- **البحث عن العملاء** بالاسم أو رقم الهاتف
- **تطبيق الخصم تلقائياً** عند اختيار العميل
- **طباعة فاتورة مسودة** (غير مدفوعة) للمطبخ
- **طرق دفع متعددة** (نقد، بطاقة، تحويل بنكي، أخرى)
- **حماية حذف الأصناف** بكلمة سر
- **إعدادات منفصلة** لكل فرع

## 📁 الملفات الجديدة:

### Templates:
- `templates/china_town_sales.html` - واجهة China Town POS
- `templates/palace_india_sales.html` - واجهة Palace India POS
- `templates/sales_branches.html` - صفحة اختيار الفروع
- `templates/sales_redirect.html` - صفحة التوجيه للنظام الجديد

### Scripts:
- `migrations/add_branch_settings.py` - migration لإضافة إعدادات الفروع
- `link_existing_meals.py` - ربط الوجبات الموجودة بالفئات
- `test_new_pos_system.py` - اختبارات شاملة للنظام
- `run_server.py` - script لتشغيل الخادم

### Documentation:
- `NEW_POS_SYSTEM_README.md` - دليل النظام الجديد
- `ADD_MORE_MEALS_GUIDE.md` - دليل إضافة الوجبات

## 🔧 خطوات النشر:

### 1. تطبيق التغييرات:
```bash
# إذا كان لديك access للمستودع:
git fetch origin
git checkout feature/new-pos-system
git merge main

# أو تطبيق الـ patch:
git apply new-pos-system.patch
```

### 2. تشغيل Migration:
```bash
python migrations/add_branch_settings.py
# أو
python add_branch_settings_simple.py
```

### 3. ربط الوجبات الموجودة:
```bash
python link_existing_meals.py
```

### 4. اختبار النظام:
```bash
python test_new_pos_system.py
```

### 5. تشغيل الخادم:
```bash
python run_server.py
# أو
python app.py
```

## 🌐 الروابط الجديدة:

- **اختيار الفروع**: http://localhost:5000/sales
- **China Town POS**: http://localhost:5000/sales/china_town
- **Palace India POS**: http://localhost:5000/sales/palace_india
- **الإعدادات**: http://localhost:5000/settings

## ⚙️ الإعدادات الجديدة:

تم إضافة الحقول التالية لجدول `Settings`:
- `china_town_void_password` (افتراضي: '1991')
- `china_town_vat_rate` (افتراضي: 15.00)
- `china_town_discount_rate` (افتراضي: 0.00)
- `place_india_void_password` (افتراضي: '1991')
- `place_india_vat_rate` (افتراضي: 15.00)
- `place_india_discount_rate` (افتراضي: 0.00)

## 🧪 الاختبار:

النظام تم اختباره بالكامل:
- ✅ قاعدة البيانات (5/5)
- ✅ الروابط (4/4)
- ✅ API endpoints (7/7)
- ✅ دوال المساعدة (2/2)
- ✅ ملفات القوالب (5/5)

## 📊 البيانات الحالية:

- **18 فئة رئيسية** في MenuCategory
- **10 وجبات** مربوطة بالفئات
- **3 فئات نشطة**: House Special (7 وجبات), Chicken (2 وجبات), Rice & Biryani (1 وجبة)

## 🔑 بيانات الدخول:

- **Username**: admin
- **Password**: admin

## 📞 الدعم:

إذا واجهت أي مشاكل:
1. تأكد من تشغيل migration
2. تأكد من ربط الوجبات بالفئات
3. شغل الاختبارات للتأكد من سلامة النظام
4. تحقق من console المتصفح للأخطاء

---

**🎯 النظام جاهز للإنتاج!**
