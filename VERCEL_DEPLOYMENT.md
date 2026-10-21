# دليل نشر مشروع "فضفضة" على Vercel (Vercel Deployment Guide)

تم تجهيز وإعداد المشروع بالكامل ليكون متوافقاً مع منصة **Vercel** من خلال الملفات التالية:
* [`vercel.json`](file:///c:/sharing1/ML4/psychiatric_agent/vercel.json): إعدادات التوجيه (Routes) وبناء ملفات الواجهة والـ API.
* [`api/index.py`](file:///c:/sharing1/ML4/psychiatric_agent/api/index.py): مدخل دوال بايثون السحابية (Serverless Functions) لتشغيل FastAPI.
* [`requirements.txt`](file:///c:/sharing1/ML4/psychiatric_agent/requirements.txt): تعريف الحزم والمكتبات المطلوبة لبيئة Vercel.
* [`.gitignore`](file:///c:/sharing1/ML4/psychiatric_agent/.gitignore): استبعاد الملفات المؤقتة وقواعد البيانات والمفاتيح الحساسة.

---

## 1. خطوات النشر عبر Vercel Dashboard (الطريقة الأسهل والموصى بها)

### الخطوة الأولى: رفع الكود على GitHub
1. قم بإنشاء مستودع جديد على حسابك في GitHub (مثلاً: `psychiatric-agent-fadfada`).
2. قم بربط ورفع مجلد `psychiatric_agent` إلى المستودع:
   ```bash
   cd c:\sharing1\ML4\psychiatric_agent
   git init
   git add .
   git commit -m "feat: initial vercel deployment ready release"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/psychiatric-agent-fadfada.git
   git push -u origin main
   ```

### الخطوة الثانية: الاستيراد على Vercel
1. افتح موقع [Vercel](https://vercel.com/) وسجل الدخول.
2. اضغط على **"Add New..."** ثم اختر **"Project"**.
3. اختر مستودع `psychiatric-agent-fadfada` واضغط **"Import"**.
4. في شاشة الإعدادات:
   * **Framework Preset**: اتركه **Other** (يتعرف Vercel تلقائياً على `vercel.json`).
   * **Environment Variables**: أضف المتغير التالي:
     * `GEMINI_API_KEY`: المفتاح الخاص بك من Google AI Studio.
     * `MODEL_LIVE`: `gemini-3.8-live`
     * `MODEL_FLASH`: `gemini-3.8-flash`
5. اضغط على **"Deploy"**.

---

## 2. النشر عبر سطر الأوامر (Vercel CLI)

إذا كان لديك حساب Vercel مثبت ومسجل محلياً:
```bash
cd c:\sharing1\ML4\psychiatric_agent
npx vercel
```
أو للنشر مباشرة على بيئة الإنتاج:
```bash
npx vercel --prod
```

---

## 3. ملاحظة معمارية هامة بخصوص الاتصال الصوتي المباشر (WebSockets)

* دوال **Vercel Serverless Functions** تدعم وتشغل الواجهات الثابتة (`frontend/` و `design-variants/`) وكافة مسارات الـ REST API (`/health` و `/api/protocols` و `/api/crisis` و تقارير الجلسات `/api/session/.../recap` و `/api/session/.../detailed-report`).
* منصة Vercel لا تدعم اتصالات الـ WebSockets المستمرة وطويلة المدى (`/ws/live` المستخدمة في نقل دفقات الصوت PCM الحية مع Gemini Live).
* **الحل الذكي المدمج في الواجهة**:
  تم تحديث `frontend/js/app.js` ليدعم الاتصال بسيرفر الصوت المباشر تلقائياً:
  1. إذا كان التطبيق يعمل على سيرفر محلي أو كامل (مثل Render أو Railway أو VPS)، سيتصل تلقائياً بنفس النطاق.
  2. إذا كان الموقع معروضاً على Vercel (`https://fadfada.vercel.app`)، يمكنك ربطه بسيرفر الصوت بسهولة عبر تمرير المعامل في الرابط:
     ```
     https://your-fadfada.vercel.app/?backend=https://your-backend-server.com
     ```
     أو عبر ضبط `localStorage.setItem('fadfada_backend_url', 'https://your-backend-server.com')`.
