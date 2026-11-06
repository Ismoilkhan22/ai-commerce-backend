#!/bin/sh
# Kunlik PostgreSQL backup (22 §7, 25 RB-08). `backup` konteynerida cron bilan har kuni 03:00 (Asia/Tashkent).
# Qo'lda: docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod exec backup /backup/pg_backup.sh
#
#   /backups/daily/commerce_os-YYYYmmdd-HHMMSS.dump   — pg_dump --format=custom (hamma schemalar, tiklash: pg_restore)
#   /backups/daily/globals-YYYYmmdd-HHMMSS.sql        — rollar (app_runtime, app_migrator); parol xeshlari bilan
#   /backups/daily/*.sha256                           — butunlik tekshiruvi
# Saqlash: BACKUP_RETENTION_DAYS (standart 14) kundan eskisi o'chiriladi. Nusxa boshqa joyga — README "Backup".
set -eu

: "${PGHOST:=postgres}"
: "${PGUSER:=postgres}"
: "${PGDATABASE:=commerce_os}"
: "${BACKUP_DIR:=/backups/daily}"
: "${BACKUP_RETENTION_DAYS:=14}"
export PGHOST PGUSER PGDATABASE

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
umask 077  # backup'da xaridor ma'lumoti bor (shifrlangan maydonlar ham) — faqat egasi o'qiydi

dump="$BACKUP_DIR/${PGDATABASE}-${stamp}.dump"
globals="$BACKUP_DIR/globals-${stamp}.sql"

echo "{\"event\":\"backup.started\",\"service\":\"backup\",\"file\":\"$(basename "$dump")\"}"
pg_dump --format=custom --compress=6 --file="$dump.partial"
pg_dumpall --globals-only --file="$globals.partial"
mv "$dump.partial" "$dump"
mv "$globals.partial" "$globals"

# Dump o'qiladimi (arxiv mundarijasi) — buzilgan fayl jim saqlanib qolmasin
pg_restore --list "$dump" >/dev/null
(cd "$BACKUP_DIR" && sha256sum "$(basename "$dump")" "$(basename "$globals")" > "${PGDATABASE}-${stamp}.sha256")

size="$(du -h "$dump" | cut -f1)"
find "$BACKUP_DIR" -type f \( -name '*.dump' -o -name '*.sql' -o -name '*.sha256' -o -name '*.partial' \) \
    -mtime +"$BACKUP_RETENTION_DAYS" -print -delete
echo "{\"event\":\"backup.finished\",\"service\":\"backup\",\"file\":\"$(basename "$dump")\",\"size\":\"$size\"}"

# Muvaffaqiyat signali (ixtiyoriy): healthchecks.io yoki shunga o'xshash — signal kelmasa founder'ga xabar
if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    wget -q -O /dev/null -T 10 "$BACKUP_HEARTBEAT_URL" || echo '{"event":"backup.heartbeat_failed","service":"backup"}'
fi
