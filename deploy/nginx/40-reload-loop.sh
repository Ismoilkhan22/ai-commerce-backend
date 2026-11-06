#!/bin/sh
# Rasmiy entrypoint (/docker-entrypoint.d) ishga tushiradi: certbot yangilagan sertifikatni olish uchun
# har 6 soatda yumshoq `nginx -s reload` (ulanishlar uzilmaydi). Fon jarayoni — entrypoint davom etadi.
(while :; do sleep 21600; nginx -s reload 2>/dev/null || true; done) &
