[app]
title = TG Cleaner
package.name = tgcleaner
package.domain = org.tgcleaner
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0
requirements = python3,kivy==2.3.0,sqlite3,telethon,pyaes,rsa,pyasn1
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #000000

android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True

p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
