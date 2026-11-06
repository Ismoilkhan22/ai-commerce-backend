#!/bin/sh
# backup konteyneri: busybox crond, har kuni BACKUP_CRON (standart 03:00) da pg_backup.sh
set -eu
echo "${BACKUP_CRON:-0 3 * * *} /backup/pg_backup.sh >> /proc/1/fd/1 2>&1" | crontab -
echo "{\"event\":\"backup.scheduler_started\",\"service\":\"backup\",\"cron\":\"${BACKUP_CRON:-0 3 * * *}\"}"
exec crond -f -l 8
