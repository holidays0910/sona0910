[app]

# (str) Title of your application
title = Burgman ESP32

# (str) Package name
package.name = burgmanesp32

# (str) Package domain (kailangan unique, reverse-domain style)
package.domain = org.yourdomain

# (str) Source code kung nasaan ang main.py
source.dir = .

# (list) Source files na isasama (mga extensions)
source.include_exts = py,png,jpg,kv,atlas

# (str) Application versioning
version = 1.0

# (list) Application requirements
# pyjnius = para makausap ang Android Java APIs (Bluetooth)
requirements = python3,kivy==2.3.0,pyjnius

# (str) Icon ng app (optional - pwede kang maglagay ng icon.png dito)
#icon.filename = %(source.dir)s/icon.png

# (str) Supported orientation (portrait, landscape, o all)
orientation = portrait

# (bool) Fullscreen application
fullscreen = 0

# ---------------------------------------------------------------------------
# ANDROID SPECIFIC
# ---------------------------------------------------------------------------

# (list) Permissions - ito ang mga kailangan para gumana ang Classic Bluetooth
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_SCAN,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION

# (int) Target Android API - dapat kasabay ng modernong Play Store requirements
android.api = 33

# (int) Minimum API na susuportahan (21 = Android 5.0, sakop halos lahat ng phone)
android.minapi = 21

# (str) Android NDK version na gagamitin
android.ndk = 25b

# (bool) Gamitin ang AndroidX libraries (kailangan para sa bagong Android)
android.enable_androidx = True

# (list) Android archs na i-bubuild (arm64-v8a ang pinaka-common ngayon)
android.archs = arm64-v8a, armeabi-v7a

# (bool) Kung gusto mo ng debug build na naka-auto-accept ng SDK licenses
android.accept_sdk_license = True

# (int) Version code (bilang - taasan ito sa bawat bagong release)
android.numeric_version = 1

[buildozer]

# (int) Log level (0 = error lang, 1 = info, 2 = debug/verbose)
log_level = 2

# (int) Warn kapag naka-run bilang root (huwag baguhin)
warn_on_root = 1
