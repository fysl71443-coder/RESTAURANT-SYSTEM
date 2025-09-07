# 📋 دليل إضافة الوجبات للمنيو

## 🎯 الوضع الحالي

✅ **تم إصلاح المشكلة!** النظام الآن يعرض:
- **18 فئة رئيسية** (Appetizers, Soups, Chicken, etc.)
- **10 وجبات مربوطة** بالفئات المناسبة
- **نظام POS يعمل** ويعرض الفئات والوجبات

## 🔍 ما تم اكتشافه

النظام يحتوي على:
- ✅ 18 فئة رئيسية في `MenuCategory`
- ✅ 10 وجبات في `Meal` (وليس 204 كما ذُكر)
- ✅ تم ربط الوجبات بالفئات في `MenuItem`

## 📝 كيفية إضافة المزيد من الوجبات

### الطريقة الأولى: من خلال واجهة الويب
1. **الدخول للنظام**: http://127.0.0.1:5000
2. **الذهاب للمنيو**: http://127.0.0.1:5000/menu
3. **إضافة وجبة جديدة**:
   - اذهب إلى "Meals" → "Add New Meal"
   - أدخل اسم الوجبة (عربي وإنجليزي)
   - حدد الفئة
   - أدخل السعر
   - احفظ
4. **ربط الوجبة بالمنيو**:
   - في صفحة Menu، اختر الفئة
   - اضغط "Add Item"
   - اختر الوجبة من القائمة
   - احفظ

### الطريقة الثانية: استيراد من ملف CSV
```python
# إنشاء ملف meals.csv بالتنسيق التالي:
# name,name_ar,category,price,description
# Chicken Tikka,تكا دجاج,Chicken,25.00,Grilled chicken pieces
# Beef Kabsa,كبسة لحم,Rice & Biryani,30.00,Traditional rice dish
```

### الطريقة الثالثة: إضافة برمجية
```python
from app import app, db
from models import Meal, MenuCategory, MenuItem

with app.app_context():
    # إنشاء وجبة جديدة
    meal = Meal(
        name="Chicken Tikka",
        name_ar="تكا دجاج", 
        category="Chicken",
        selling_price=25.00,
        active=True,
        user_id=1  # ID المستخدم
    )
    db.session.add(meal)
    db.session.flush()
    
    # ربطها بفئة في المنيو
    category = MenuCategory.query.filter_by(name="Chicken").first()
    if category:
        menu_item = MenuItem(
            category_id=category.id,
            meal_id=meal.id
        )
        db.session.add(menu_item)
    
    db.session.commit()
```

## 🏗️ إنشاء script لإضافة وجبات متعددة

إذا كان لديك قائمة بالوجبات، يمكنني إنشاء script لإضافتها بسرعة:

```python
# مثال على البيانات المطلوبة
meals_data = [
    {"name": "Chicken Tikka", "name_ar": "تكا دجاج", "category": "Chicken", "price": 25.00},
    {"name": "Beef Kabsa", "name_ar": "كبسة لحم", "category": "Rice & Biryani", "price": 30.00},
    {"name": "Fish Curry", "name_ar": "كاري سمك", "category": "Seafoods", "price": 28.00},
    # ... المزيد من الوجبات
]
```

## 📊 الفئات المتاحة حالياً

1. **Appetizers** - المقبلات
2. **Soups** - الشوربات  
3. **Salads** - السلطات
4. **House Special** - أطباق المطعم الخاصة
5. **Prawns** - الجمبري
6. **Seafoods** - المأكولات البحرية
7. **Chinese Sizzling** - الأطباق الصينية الساخنة
8. **Shaw Faw** - شاو فاو
9. **Chicken** - الدجاج
10. **Beef & Lamb** - اللحم والخروف
11. **Rice & Biryani** - الأرز والبرياني
12. **Noodles & Chopsuey** - النودلز والتشوبسي
13. **Charcoal Grill / Kebabs** - المشاوي والكباب
14. **Indian Delicacy (Chicken)** - الأطباق الهندية (دجاج)
15. **Indian Delicacy (Fish)** - الأطباق الهندية (سمك)
16. **Indian Delicacy (Vegetables)** - الأطباق الهندية (خضار)
17. **Juices** - العصائر
18. **Soft Drink** - المشروبات الغازية

## 🚀 الخطوات التالية

1. **اختبر النظام الحالي**: تأكد أن الوجبات الـ 10 تظهر في POS
2. **أضف المزيد من الوجبات**: استخدم إحدى الطرق أعلاه
3. **تنظيم الفئات**: تأكد أن كل وجبة في الفئة المناسبة
4. **تحديث الأسعار**: تأكد أن جميع الأسعار صحيحة

## 💡 نصائح

- **استخدم أسماء واضحة** للوجبات (عربي وإنجليزي)
- **حدد الفئة المناسبة** لكل وجبة
- **تأكد من الأسعار** قبل الحفظ
- **اختبر في POS** بعد كل إضافة

---

**🎉 النظام جاهز الآن ويعرض الوجبات في POS!**

للاختبار: http://127.0.0.1:5000/sales/china_town
