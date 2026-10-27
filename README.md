# TG Cleaner

## របៀប build APK ដោយ GitHub
1. បង្កើត repo ថ្មីក្នុង GitHub
2. Upload ឯកសារទាំងអស់ក្នុង ZIP នេះ (ត្រូវរក្សា folder `.github/workflows/`)
3. ចូល tab **Actions** → រង់ចាំ build (ប្រហែល 20-40 នាទីលើកដំបូង)
4. ចុចលើ run ដែលជោគជ័យ → **Artifacts** → ទាញយក `tgcleaner-apk`

## របៀបប្រើ
1. យក API ID / API Hash ពី https://my.telegram.org → API development tools
2. បញ្ចូល API ID, API Hash, លេខទូរស័ព្ទ → Connect
3. បញ្ចូលកូដដែល Telegram ផ្ញើ (និងលេខសម្ងាត់ 2FA បើមាន)
4. ចុច Clean account → វាយ DELETE ដើម្បីបញ្ជាក់
5. History បង្ហាញខាងក្រោម ហើយរក្សាទុកក្នុងទូរស័ព្ទ

## ចំណាំ
- ការលុបមិនអាចត្រឡប់វិញបានទេ
- បើ Telegram កំណត់ limit app នឹងរង់ចាំដោយស្វ័យប្រវត្តិ
- កុំបិទ app ឬ lock អេក្រង់ ពេលកំពុងសម្អាត
- ប្រើបានតែលើគណនីរបស់អ្នកផ្ទាល់
