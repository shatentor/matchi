#!/usr/bin/env bash
#
# Восстановление дампа Matchi в УКАЗАННУЮ базу.
#
#   ./scripts/restore_db.sh <файл.dump> <имя_целевой_базы>
#
# Целевая база задаётся аргументом, а не берётся из .env, и восстановление
# требует ввода `yes`: иначе одна опечатка затирает рабочую базу. Восстановление
# в рабочую базу (DB_NAME из .env) дополнительно закрыто — снимается только
# явным ALLOW_PROD_RESTORE=yes в окружении.
#
# Код выхода: 0 — база восстановлена, 1 — любая ошибка или отказ подтвердить.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
    printf '[%s] ОШИБКА: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
    exit 1
}

usage() {
    printf 'Использование: %s <файл.dump> <имя_целевой_базы>\n' "$0" >&2
    printf 'Пример: %s ~/.local/share/matchi-backups/match_bot-20260729-030000.dump matchi_restore_test\n' "$0" >&2
}

# Значение переменной из .env. Файл не выполняется: в нём пароль и токен бота.
env_file_get() {
    local key="$1" line value
    [ -f "${ENV_FILE}" ] || return 0
    line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${ENV_FILE}" | tail -n 1)" || true
    [ -n "${line}" ] || return 0
    value="${line#*=}"
    value="${value%$'\r'}"
    if [ ${#value} -ge 2 ]; then
        case "${value}" in
            \"*\") value="${value:1:${#value}-2}" ;;
            \'*\') value="${value:1:${#value}-2}" ;;
        esac
    fi
    printf '%s' "${value}"
}

# Приоритет: окружение → .env → значение по умолчанию.
resolve() {
    local name="$1" default="${2-}" value
    value="${!name-}"
    if [ -n "${value}" ]; then
        printf '%s' "${value}"
        return 0
    fi
    value="$(env_file_get "${name}")"
    if [ -n "${value}" ]; then
        printf '%s' "${value}"
        return 0
    fi
    printf '%s' "${default}"
}

require() {
    local name="$1" value
    value="$(resolve "${name}")"
    [ -n "${value}" ] || die "не задано ${name} — ни в окружении, ни в ${ENV_FILE}"
    printf '%s' "${value}"
}

if [ "$#" -ne 2 ]; then
    usage
    die "нужно ровно два аргумента: файл дампа и имя целевой базы"
fi

DUMP_FILE="$1"
TARGET_DB="$2"

[ -f "${DUMP_FILE}" ] || die "файл дампа не найден: ${DUMP_FILE}"
[ -r "${DUMP_FILE}" ] || die "файл дампа недоступен для чтения: ${DUMP_FILE}"
[ -s "${DUMP_FILE}" ] || die "файл дампа пуст: ${DUMP_FILE}"

DB_USER="$(require DB_USER)"
DB_HOST="$(require DB_HOST)"
DB_PORT="$(require DB_PORT)"
WORKING_DB="$(require DB_NAME)"
DB_PASSWORD="$(resolve DB_PASSWORD)"
PG_BIN_DIR="$(resolve PG_BIN_DIR /usr/lib/postgresql/16/bin)"

case "${DB_PORT}" in
    ''|*[!0-9]*) die "DB_PORT должен быть целым числом, получено: ${DB_PORT}" ;;
esac
if [ "${DB_PORT}" = "5432" ]; then
    log "ВНИМАНИЕ: порт 5432. На машине разработки он занят SSH-туннелем к чужой базе,"
    log "         локальный кластер Matchi слушает 5433. Проверьте DB_PORT."
fi

if [ "${TARGET_DB}" = "${WORKING_DB}" ] && [ "${ALLOW_PROD_RESTORE:-}" != "yes" ]; then
    die "целевая база «${TARGET_DB}» — рабочая база проекта. Восстанавливайте в отдельную базу, а если это осознанное восстановление после аварии, запустите с ALLOW_PROD_RESTORE=yes"
fi

PG_RESTORE="${PG_BIN_DIR}/pg_restore"
PSQL="${PG_BIN_DIR}/psql"
CREATEDB="${PG_BIN_DIR}/createdb"
for bin in "${PG_RESTORE}" "${PSQL}" "${CREATEDB}"; do
    [ -x "${bin}" ] || die "не найден ${bin} (PG_BIN_DIR=${PG_BIN_DIR}); серверных бинарников PostgreSQL нет в PATH"
done

# Пароль — только в окружении процесса, не в аргументах: аргументы видны в `ps`.
if [ -n "${DB_PASSWORD}" ]; then
    export PGPASSWORD="${DB_PASSWORD}"
fi
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

# Битый дамп не должен затирать содержимое целевой базы — проверяем до вопроса.
LISTING="$(mktemp)"
trap 'rm -f "${LISTING}"' EXIT
if ! "${PG_RESTORE}" --list "${DUMP_FILE}" >"${LISTING}" 2>&1; then
    sed 's/^/    pg_restore: /' "${LISTING}" >&2 || true
    die "дамп не читается pg_restore --list, восстанавливать нечего: ${DUMP_FILE}"
fi
DUMP_TABLES="$(grep -c ' TABLE DATA ' "${LISTING}")" || DUMP_TABLES=0

log "дамп:            ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1), таблиц с данными: ${DUMP_TABLES})"
log "целевая база:    ${TARGET_DB} на ${DB_HOST}:${DB_PORT}"
log "рабочая база:    ${WORKING_DB} (её не трогаем)"

db_exists() {
    local out
    out="$("${PSQL}" --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
        --dbname=postgres --no-password --no-align --tuples-only \
        --command="SELECT 1 FROM pg_database WHERE datname = '${1}'" 2>&1)" || {
        printf '%s\n' "${out}" | sed 's/^/    psql: /' >&2
        die "не удалось подключиться к ${DB_HOST}:${DB_PORT} (кластер поднят? доступы в ${ENV_FILE} верны?)"
    }
    [ "${out}" = "1" ]
}

if db_exists "${TARGET_DB}"; then
    log "база ${TARGET_DB} уже существует — её содержимое будет ЗАМЕНЕНО содержимым дампа"
    TARGET_EXISTED="yes"
else
    log "базы ${TARGET_DB} нет — она будет создана"
    TARGET_EXISTED="no"
fi

printf 'Восстановить дамп в базу «%s» на %s:%s? Введите yes для продолжения: ' \
    "${TARGET_DB}" "${DB_HOST}" "${DB_PORT}"
CONFIRM=""
IFS= read -r CONFIRM || true
if [ "${CONFIRM}" != "yes" ]; then
    die "подтверждение не получено (введено «${CONFIRM}»), ничего не менялось"
fi

if [ "${TARGET_EXISTED}" = "no" ]; then
    "${CREATEDB}" --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
        --no-password "${TARGET_DB}" || die "не удалось создать базу ${TARGET_DB}"
    log "база ${TARGET_DB} создана"
fi

log "восстановление начато"
# --clean --if-exists: повторный прогон в непустую базу должен заменять объекты,
# а не падать на уже существующих. --no-owner/--no-privileges: владельцы и гранты
# из дампа могут не существовать в целевом кластере.
if ! "${PG_RESTORE}" \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --username="${DB_USER}" \
        --dbname="${TARGET_DB}" \
        --no-password \
        --clean --if-exists \
        --no-owner --no-privileges \
        --exit-on-error \
        "${DUMP_FILE}"; then
    die "pg_restore завершился с ошибкой, база ${TARGET_DB} может быть в неполном состоянии"
fi

TABLE_COUNT="$("${PSQL}" --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
    --dbname="${TARGET_DB}" --no-password --no-align --tuples-only \
    --command="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")" \
    || die "восстановление прошло, но проверочный запрос к ${TARGET_DB} не выполнился"

log "готово: в ${TARGET_DB} таблиц в схеме public: ${TABLE_COUNT}"

for tbl in users posts; do
    rows="$("${PSQL}" --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
        --dbname="${TARGET_DB}" --no-password --no-align --tuples-only \
        --command="SELECT count(*) FROM ${tbl}" 2>/dev/null)" || rows="таблицы нет"
    log "  ${tbl}: ${rows}"
done

exit 0
