[app]
# (str) Title of your application
title = N.I BUSINESS

# (str) Package name
package.name = business

# (str) Package domain (needed for android packaging)
package.domain = com.niforever

# (str) Source code where the main.py lives
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf

# (str) Application versioning
version = 3.4

# (list) Application requirements
requirements = python3,kivy==2.3.0,reportlab,sqlite3

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

# (int) Target Android API
android.api = 34
android.minapi = 21
android.ndk = 25b

# (bool) Copy library instead of making a libpymodules.so
android.copy_libs = 1

# (str) Icon of the application
icon.filename = %(source.dir)s/icon.png

# (str) Presplash of the application
presplash.filename = %(source.dir)s/presplash.png

[buildozer]
# (int) Log level (0 = error only, 1 = info, 2 = debug with command output)
log_level = 2
warn_on_root = 1
